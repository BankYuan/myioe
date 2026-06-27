"""
对外只读 API —— 供内容平台(xhs-content-platform)拉取鞋款原料数据。

设计要点:
- 仅暴露 GET,不挂 @login_required(供服务端到服务端调用),用 X-Api-Key 鉴权。
- 按款号(model_no)聚合输出:一个鞋款 = 一个 model_no 下所有 SKU(颜色/尺码)。
- 图片返回绝对 URL(request.build_absolute_uri),依赖 settings.MEDIA_URL 为 '/media/'。
- 不引入 DRF / CORS;GET 天然免 CSRF。
"""
import hmac

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, F, Max, Min, Sum
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from inventory.models import Category, Product, ProductImage

# 画像字段的中文展示映射(取自 Product choices)
_SEASON_LABELS = dict(Product.SEASON_CHOICES)
_AUDIENCE_LABELS = dict(Product.AUDIENCE_CHOICES)


def _category_pair(cat_code, cat_l1):
    """根据分类 code 与 l1_code 判定 category_l1 / category_l2。"""
    cat_code = cat_code or ''
    cat_l1 = cat_l1 or ''
    if cat_code and cat_code != cat_l1:
        return cat_l1, cat_code  # 选了二级类目(L2)
    return cat_code, ''  # 选了一级类目(L1)或无分类


def _l1_name_map():
    """一级类目 code -> 中文名 映射(每次请求查,保证 seed 后即时生效)。"""
    return dict(
        Category.objects.filter(code=F('l1_code')).exclude(code='').values_list('code', 'name')
    )


# ---------- 工具函数 ----------

def _to_int(val, default):
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _abs_url(request, rel):
    """把媒体相对路径拼成绝对 URL;MEDIA_URL 已含前导斜杠。"""
    if not rel:
        return None
    rel = str(rel).lstrip('/')
    return request.build_absolute_uri(settings.MEDIA_URL + rel)


def _check_api_key(request):
    """校验 X-Api-Key。返回 None 表示通过,否则返回应直接 return 的 JsonResponse。"""
    expected = getattr(settings, 'XHS_API_KEY', '')
    if not expected:
        return JsonResponse(
            {'success': False, 'error': 'API key 未在服务端配置(XHS_API_KEY)'},
            status=503,
        )
    provided = request.headers.get('X-Api-Key') or request.META.get('HTTP_X_API_KEY', '')
    if not provided or not hmac.compare_digest(str(provided), str(expected)):
        return JsonResponse(
            {'success': False, 'error': '无效或缺失的 API key'},
            status=401,
        )
    return None


def _model_main_image_url(request, model_no):
    """取该款的主图 URL:优先 ProductImage(image_type='main'),回退到 Product.image。"""
    primary_img = (
        ProductImage.objects
        .filter(product__model_no=model_no, image_type='main', image__isnull=False)
        .exclude(image='')
        .first()
    )
    if primary_img and primary_img.image:
        return _abs_url(request, primary_img.image.name)
    p = Product.objects.filter(model_no=model_no).exclude(image='').first()
    if p and p.image:
        return _abs_url(request, p.image.name)
    return None


# ---------- 视图 ----------

@require_GET
def api_shoe_models(request):
    """鞋款列表(按款号聚合)。

    GET 参数:
      page      页码,默认 1
      page_size 每页数,默认 20,上限 100
    """
    auth_err = _check_api_key(request)
    if auth_err:
        return auth_err

    page = max(1, _to_int(request.GET.get('page', 1), 1))
    page_size = min(100, max(1, _to_int(request.GET.get('page_size', 20), 20)))

    models = (
        Product.objects
        .filter(is_active=True, model_no__gt='')
        .values('model_no')
        .annotate(
            name=Max('name'),
            cat_l1=Max('category__l1_code'),
            cat_code=Max('category__code'),
            category_l1_label=Max('category__name'),
            category_name=Max('category__name'),
            sku_count=Count('id'),
            color_count=Count('color', distinct=True),
            size_count=Count('size', distinct=True),
            total_stock=Sum('inventory__quantity'),
            price_min=Min('price'),
            price_max=Max('price'),
            brand=Max('brand'),
            season=Max('season'),
            audience=Max('audience'),
        )
        .order_by('model_no')
    )

    paginator = Paginator(models, page_size)
    page_obj = paginator.get_page(page)

    l1_names = _l1_name_map()
    items = []
    for m in page_obj.object_list:
        category_l1, category_l2 = _category_pair(m['cat_code'], m['cat_l1'])
        season = m['season'] or ''
        audience = m['audience'] or ''
        items.append({
            'model_no': m['model_no'],
            'name': m['name'],
            'category_l1': category_l1,
            'category_l2': category_l2,
            'category_l1_label': l1_names.get(category_l1, ''),
            'main_image': _model_main_image_url(request, m['model_no']),  # TODO: 列表 N+1,款数大时需优化为子查询
            'brand': m['brand'] or '',
            'season': season,
            'season_label': _SEASON_LABELS.get(season, '') if season else '',
            'audience': audience,
            'audience_label': _AUDIENCE_LABELS.get(audience, '') if audience else '',
            'sku_count': m['sku_count'],
            'color_count': m['color_count'],
            'size_count': m['size_count'],
            'total_stock': m['total_stock'] or 0,
            'price_min': str(m['price_min']) if m['price_min'] is not None else None,
            'price_max': str(m['price_max']) if m['price_max'] is not None else None,
        })

    return JsonResponse({
        'success': True,
        'page': page_obj.number,
        'page_size': page_size,
        'total': paginator.count,
        'items': items,
    })


@require_GET
def api_shoe_model_detail(request, model_no):
    """单款详情(含全部 SKU 明细与图片)。"""
    auth_err = _check_api_key(request)
    if auth_err:
        return auth_err

    products = (
        Product.objects
        .filter(model_no=model_no, is_active=True)
        .select_related('category')
    )
    if not products.exists():
        return JsonResponse(
            {'success': False, 'error': f'未找到款号 {model_no}'},
            status=404,
        )

    agg = products.aggregate(
        name=Max('name'),
        cat_l1=Max('category__l1_code'),
        cat_code=Max('category__code'),
        category_l1_label=Max('category__name'),
        category_name=Max('category__name'),
        description=Max('description'),
        manufacturer=Max('manufacturer'),
        brand=Max('brand'),
        season=Max('season'),
        audience=Max('audience'),
        total_stock=Sum('inventory__quantity'),
        sku_count=Count('id'),
    )
    category_l1, category_l2 = _category_pair(agg['cat_code'], agg['cat_l1'])
    season = agg['season'] or ''
    audience = agg['audience'] or ''
    l1_names = _l1_name_map()

    # 按 image_type 分组的图片(主图/侧面/鞋底/细节/上脚)
    images_by_type = {code: [] for code, _ in ProductImage.IMAGE_TYPES}
    for img in ProductImage.objects.filter(product__model_no=model_no).order_by('image_type', 'order'):
        url = _abs_url(request, img.image.name if img.image else None)
        if url:
            images_by_type[img.image_type].append(url)
    all_images = [u for urls in images_by_type.values() for u in urls]
    main_image = images_by_type['main'][0] if images_by_type['main'] else (all_images[0] if all_images else None)

    skus = []
    for p in products:
        inv = getattr(p, 'inventory', None)  # Inventory 与 Product 是 OneToOne,反查关系名为 inventory
        skus.append({
            'barcode': p.barcode,
            'color': p.color,
            'color_label': p.get_color_display() if p.color else '',
            'size': p.size,
            'price': str(p.price),
            'cost': str(p.cost),
            'stock': inv.quantity if inv else 0,
            'is_active': p.is_active,
        })

    return JsonResponse({
        'success': True,
        'model_no': model_no,
        'name': agg['name'],
        'category_l1': category_l1,
        'category_l2': category_l2,
        'category_l1_label': l1_names.get(category_l1, ''),
        'category_name': agg['category_name'] or '',
        'description': agg['description'] or '',
        'manufacturer': agg['manufacturer'] or '',
        'brand': agg['brand'] or '',
        'season': season,
        'season_label': _SEASON_LABELS.get(season, '') if season else '',
        'audience': audience,
        'audience_label': _AUDIENCE_LABELS.get(audience, '') if audience else '',
        'main_image': main_image,
        'all_images': all_images,
        'images_by_type': images_by_type,
        'skus': skus,
        'total_stock': agg['total_stock'] or 0,
        'sku_count': agg['sku_count'],
    })
