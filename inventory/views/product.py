from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.db.models import Q, Count, Sum
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import timezone

import csv
import io
import base64
import uuid
import os
from PIL import Image
from datetime import datetime

from inventory.models import (
    Product, Category, ProductImage, ProductBatch,
    Inventory, InventoryTransaction, Supplier
)
from inventory.forms import (
    ProductForm, CategoryForm, ProductBatchForm,
    ProductImageFormSet, ProductImportForm
)
from inventory.utils import generate_thumbnail, validate_csv
from inventory.services import product_service


def product_by_barcode(request, barcode):
    """根据条码查询商品信息的API"""
    try:
        # 先尝试精确匹配条码
        product = Product.objects.get(barcode=barcode)
        # 获取库存信息
        try:
            inventory_obj = Inventory.objects.get(product=product)
            stock = inventory_obj.quantity
        except Inventory.DoesNotExist:
            stock = 0
            
        return JsonResponse({
            'success': True,
            'product_id': product.id,
            'name': product.name,
            'price': float(product.price),
            'stock': stock,
            'category': product.category.name if product.category else '',
            'specification': product.specification,
            'manufacturer': product.manufacturer
        })
    except Product.DoesNotExist:
        # 如果精确匹配失败，尝试模糊匹配条码
        try:
            products = Product.objects.filter(barcode__icontains=barcode).order_by('barcode')[:5]
            
            if products.exists():
                # 返回匹配的多个商品
                product_list = []
                for product in products:
                    try:
                        inventory_obj = Inventory.objects.get(product=product)
                        stock = inventory_obj.quantity
                    except Inventory.DoesNotExist:
                        stock = 0
                        
                    product_list.append({
                        'product_id': product.id,
                        'barcode': product.barcode,
                        'name': product.name,
                        'price': float(product.price),
                        'stock': stock
                    })
                    
                return JsonResponse({
                    'success': True,
                    'multiple_matches': True,
                    'products': product_list
                })
            else:
                return JsonResponse({'success': False, 'message': '未找到商品'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'查询时发生错误: {str(e)}'})


@login_required
def product_list(request):
    """商品列表视图"""
    # 获取筛选参数
    search_query = request.GET.get('search', '')
    category_id = request.GET.get('category', '')
    status = request.GET.get('status', 'active')  # 默认显示活跃商品
    sort_by = request.GET.get('sort', 'updated')  # 修改默认排序为更新时间
    supplier_id = request.GET.get('supplier', '')
    
    print(f"DEBUG: 列表筛选参数 - 搜索: {search_query}, 分类: {category_id}, 状态: {status}, 排序: {sort_by}")
    
    # 基本查询集
    products = Product.objects.select_related('category', 'supplier').all()
    print(f"DEBUG: 初始查询集数量: {products.count()}")
    
    # 应用筛选
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) | 
            Q(barcode__icontains=search_query) |
            Q(specification__icontains=search_query)
        )
    
    if category_id:
        try:
            cat = Category.objects.get(id=category_id)
            if cat.code and cat.code == cat.l1_code:
                # 选的是一级类目:把它名下所有二级类目的商品也查出来
                sub_ids = list(Category.objects.filter(l1_code=cat.code).values_list('id', flat=True))
                products = products.filter(category_id__in=sub_ids)
            else:
                products = products.filter(category_id=category_id)
        except Category.DoesNotExist:
            products = products.filter(category_id=category_id)

    if supplier_id:
        products = products.filter(supplier_id=supplier_id)

    # 状态筛选
    if status == 'active':
        products = products.filter(is_active=True)
        print(f"DEBUG: 应用活跃状态筛选后的数量: {products.count()}")
    elif status == 'inactive':
        products = products.filter(is_active=False)
    
    # 排序
    if sort_by == 'name':
        products = products.order_by('name')
    elif sort_by == 'price':
        products = products.order_by('price')
    elif sort_by == 'category':
        products = products.order_by('category__name', 'name')
    elif sort_by == 'created':
        products = products.order_by('-created_at')
    elif sort_by == 'updated':  # 添加按更新时间排序
        products = products.order_by('-updated_at')
    else:  # 默认按更新时间降序
        products = products.order_by('-updated_at')
    
    # 批量取库存,避免 N+1
    inv_map = {i.product_id: (i.quantity, i.warning_level)
               for i in Inventory.objects.filter(product__in=products)}

    # 按 model_no(款号)聚合成款组;无款号的按条码各自独立成组
    from collections import OrderedDict
    groups = OrderedDict()
    for p in products:
        key = p.model_no.strip() if (p.model_no and p.model_no.strip()) else f'_nobar_{p.barcode}'
        g = groups.get(key)
        if g is None:
            g = {
                'key': key, 'model_no': p.model_no, 'name': p.name,
                'image': p.image, 'category': p.category, 'supplier': p.supplier,
                'price': p.price, 'is_active': p.is_active,
                'colors': [], 'sizes': [], 'skus': [], 'total_stock': 0, 'low_count': 0,
                'updated_at': p.updated_at,
            }
            groups[key] = g
        inv_info = inv_map.get(p.id)
        stock = inv_info[0] if inv_info else 0
        warning_level = inv_info[1] if inv_info else 1
        # 款图可能挂在同款其他 SKU(款主)上,补全款组缩略图:任一 SKU 有图就用
        if not g['image'] and p.image:
            g['image'] = p.image
        g['skus'].append({
            'id': p.id, 'barcode': p.barcode, 'color': p.color, 'size': p.size,
            'stock': stock, 'price': p.price, 'is_active': p.is_active,
        })
        g['total_stock'] += stock
        if stock <= warning_level:
            g['low_count'] += 1
        if p.color and p.color not in g['colors']:
            g['colors'].append(p.color)
        if p.size and p.size not in g['sizes']:
            g['sizes'].append(p.size)
        if p.updated_at > g['updated_at']:
            g['updated_at'] = p.updated_at
    product_groups = list(groups.values())

    # 款级分页(每页 20 款)
    paginator = Paginator(product_groups, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # 当前页款组的图片池(列表缩略图点击可预览/切换该款所有图);批量查避免 N+1
    page_model_nos = {g['model_no'] for g in page_obj.object_list if g.get('model_no')}
    style_imgs = {}
    if page_model_nos:
        for pi in ProductImage.objects.filter(product__model_no__in=page_model_nos).select_related('product').order_by('order', 'id'):
            style_imgs.setdefault(pi.product.model_no, []).append(pi.image.url)
    for g in page_obj.object_list:
        if g.get('model_no'):
            g['images'] = style_imgs.get(g['model_no'], [])
        else:
            g['images'] = [g['image'].url] if g.get('image') else []

    # 获取分类列表用于筛选(按一级类目分组的 optgroup)
    from inventory.forms.product_forms import category_optgroup_choices
    category_groups = [g for g in category_optgroup_choices() if g[0]]

    # 统计
    total_products = Product.objects.count()
    active_products = Product.objects.filter(is_active=True).count()

    context = {
        'page_obj': page_obj,
        'category_groups': category_groups,
        'search_query': search_query,
        'selected_category': category_id,
        'selected_status': status,
        'sort_by': sort_by,
        'selected_supplier': supplier_id,
        'suppliers': Supplier.objects.filter(is_active=True),
        'total_products': total_products,
        'active_products': active_products,
        'product_groups': page_obj,
    }

    return render(request, 'inventory/product_list.html', context)


@login_required
def barcode_print(request):
    """条码贴纸打印页:渲染每个 SKU 的贴纸(条码=scan_code + 文字=款号/颜色/尺码),浏览器打印到标签机。"""
    ids = request.GET.get('ids', '')
    if ids:
        id_list = [i for i in ids.split(',') if i.isdigit()]
        qs = Product.objects.filter(id__in=id_list).order_by('model_no', 'id') if id_list else Product.objects.none()
    else:
        qs = Product.objects.filter(is_active=True).order_by('model_no', 'id')
    return render(request, 'inventory/product/barcode_print.html', {
        'products': qs,
    })


@login_required
def product_detail(request, pk):
    """商品详情视图"""
    product = get_object_or_404(Product, pk=pk)
    
    # 获取商品库存信息
    try:
        inventory = Inventory.objects.get(product=product)
    except Inventory.DoesNotExist:
        inventory = None
    
    # 获取商品批次信息
    batches = ProductBatch.objects.filter(product=product).order_by('-created_at')
    
    # 获取商品图片(整款共享:聚合同款所有 SKU 的图)
    images = _style_images(product)
    
    # 获取销售记录
    from inventory.models import SaleItem
    sales_history = SaleItem.objects.filter(product=product).order_by('-sale__created_at')[:10]
    
    context = {
        'product': product,
        'inventory': inventory,
        'batches': batches,
        'images': images,
        'sales_history': sales_history,
    }
    
    return render(request, 'inventory/product/product_detail.html', context)


def _save_bulk_images(product, files):
    """批量保存上传的图片(默认归主图,order 递增,生成缩略图)。供应商一堆图一次传,类型后续再整理。"""
    base = -1
    last = product.images.order_by('-order').first()
    if last:
        base = last.order
    count = 0
    for i, img in enumerate(files):
        pi = ProductImage(product=product, image=img, image_type='main', order=base + 1 + i)
        try:
            thumbnail = generate_thumbnail(img, (300, 300))
            thumb_name = f'thumb_{uuid.uuid4()}.jpg'
            thumb_path = f'products/thumbnails/{thumb_name}'
            thumb_file = io.BytesIO()
            thumbnail.save(thumb_file, format='JPEG')
            pi.thumbnail = thumb_path
        except Exception:
            pass
        pi.save()
        count += 1
    return count


def _style_owner(product):
    """款主 SKU:同款 model_no 中 id 最小的存活 SKU;无 model_no 或整款已停用则返回自己。

    图片统一归到款主,保证款内只存一份、不重复;展示则跨该款所有 SKU 聚合。
    """
    if not product.model_no:
        return product
    owner = Product.objects.filter(model_no=product.model_no, is_active=True).order_by('id').first()
    return owner or product


def _style_images(product):
    """该款(model_no)的图片池:聚合同款所有 SKU 的图片,按 order/id 排序;无 model_no 则取自身。"""
    if not product.model_no:
        return list(product.images.all())
    pks = list(Product.objects.filter(model_no=product.model_no).values_list('pk', flat=True))
    return list(ProductImage.objects.filter(product__in=pks).order_by('order', 'id'))


def _sync_style_main_image(product):
    """把款主图回填到整款所有 SKU 的 product.image 字段。

    图片按款共享存在 ProductImage 表(挂款主 SKU),但销售详情/商品详情/列表等显示用
    Product.image 字段,所以保存图片后要把款主图同步到该款每个 SKU,显示才一致。
    """
    style_imgs = _style_images(product)
    main_img = next((i for i in style_imgs if i.image_type == 'main'), None) or (style_imgs[0] if style_imgs else None)
    if not main_img or not main_img.image:
        return
    name = main_img.image.name
    if product.model_no:
        Product.objects.filter(model_no=product.model_no).exclude(image=name).update(image=name)
    elif product.image.name != name:
        product.image.name = name
        product.save(update_fields=['image'])


@login_required
def product_create(request):
    """创建商品视图"""
    if request.method == 'POST':
        form = ProductForm(request.POST)
        image_formset = ProductImageFormSet(request.POST, request.FILES, prefix='images')
        
        # 修改验证逻辑，只检查表单是否有效，不强制检查图片表单集
        if form.is_valid():
            # 保存商品数据
            product = form.save(commit=False)
            product.is_active = True  # 确保商品默认为活跃状态
            product.save()
            
            # 图片走批量上传 → 款主 SKU(整款共享,不重复存)
            _save_bulk_images(_style_owner(product), request.FILES.getlist('bulk_images'))

            # 同步款主图到整款所有 SKU 的 product.image(列表/销售/API 显示一致)
            _sync_style_main_image(product)

            # 创建初始库存记录
            warning_level = 1  # 默认预警:库存 <= 1 报警
            if 'warning_level' in form.cleaned_data and form.cleaned_data['warning_level'] is not None:
                warning_level = form.cleaned_data['warning_level']
                
            Inventory.objects.create(
                product=product,
                quantity=0,
                warning_level=warning_level
            )
            
            messages.success(request, f'商品 {product.name} 创建成功')
            
            # 如果是从批量页面过来，返回批量页面
            if 'next' in request.POST and request.POST['next'] == 'bulk':
                return redirect('product_bulk_create')
            
            # 修改重定向，解决模板不存在的问题
            return redirect('product_list')
    else:
        form = ProductForm()
        image_formset = ProductImageFormSet(prefix='images')
        
        # 如果有传入的分类参数，设置初始值
        category_id = request.GET.get('category')
        if category_id:
            try:
                form.fields['category'].initial = int(category_id)
            except (ValueError, TypeError):
                pass
    
    context = {
        'form': form,
        'style_images': [],
        'image_types': ProductImage.IMAGE_TYPES,
        'title': '创建商品',
        'submit_text': '保存商品',
        'next': request.GET.get('next', '')
    }

    return render(request, 'inventory/product/product_form.html', context)


@login_required
def product_update(request, pk):
    """更新商品视图"""
    product = get_object_or_404(Product, pk=pk)
    
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        image_formset = ProductImageFormSet(request.POST, request.FILES, prefix='images', instance=product)
        
        # 修改验证逻辑，只检查表单是否有效，不强制检查图片表单集
        if form.is_valid():
            # 保存商品数据
            product = form.save(commit=False)
            product.updated_at = timezone.now()
            product.save()
            
            # 款图片:改类型 / 删除(基于 image id,操作整款所有 SKU 的图)
            for img in _style_images(product):
                if request.POST.get('img_del_%d' % img.id) == '1':
                    img.delete()
                    continue
                new_type = request.POST.get('img_type_%d' % img.id)
                if new_type and new_type != img.image_type:
                    img.image_type = new_type
                    img.save(update_fields=['image_type'])

            # 批量上传 → 款主 SKU(整款共享)
            _save_bulk_images(_style_owner(product), request.FILES.getlist('bulk_images'))

            # 同步款主图到整款所有 SKU 的 product.image(列表/销售/API 显示一致)
            _sync_style_main_image(product)

            # 更新库存预警级别
            warning_level = 1  # 默认预警:库存 <= 1 报警
            if 'warning_level' in form.cleaned_data and form.cleaned_data['warning_level'] is not None:
                warning_level = form.cleaned_data['warning_level']
                
            try:
                inventory = Inventory.objects.get(product=product)
                inventory.warning_level = warning_level
                inventory.save()
            except Inventory.DoesNotExist:
                Inventory.objects.create(
                    product=product,
                    quantity=0,
                    warning_level=warning_level
                )
            
            messages.success(request, f'商品 {product.name} 更新成功')
            # 修改重定向，解决模板不存在的问题
            return redirect('product_list')
    else:
        form = ProductForm(instance=product)
        # 设置库存预警级别
        try:
            inventory = Inventory.objects.get(product=product)
            form.fields['warning_level'].initial = inventory.warning_level
        except Inventory.DoesNotExist:
            pass
        
        image_formset = ProductImageFormSet(prefix='images', instance=product)
    
    context = {
        'form': form,
        'style_images': _style_images(product),
        'image_types': ProductImage.IMAGE_TYPES,
        'product': product,
        'title': f'编辑商品: {product.name}',
        'submit_text': '更新商品'
    }

    return render(request, 'inventory/product/product_form.html', context)


@login_required
def product_delete(request, pk):
    """删除商品视图"""
    product = get_object_or_404(Product, pk=pk)
    
    if request.method == 'POST':
        product_name = product.name
        if request.POST.get('force') == '1':
            # 彻底删除:先把该 SKU 名下的款图片迁移给同款其他存活 SKU(图随款走,不丢),
            # 再级联清理库存/流水/销售,最后物理删商品(ProductBatch 为 CASCADE 会一并删)
            if product.model_no:
                # 图随款走:迁给同款其他存活 SKU(优先活跃),再回填主图字段,避免删后漏图
                other = (Product.objects.filter(model_no=product.model_no, is_active=True).exclude(pk=product.pk).order_by('id').first()
                         or Product.objects.filter(model_no=product.model_no).exclude(pk=product.pk).order_by('id').first())
                if other:
                    ProductImage.objects.filter(product=product).update(product=other)
                    _sync_style_main_image(other)
            Inventory.objects.filter(product=product).delete()
            InventoryTransaction.objects.filter(product=product).delete()
            try:
                from inventory.models import SaleItem
                SaleItem.objects.filter(product=product).delete()
            except Exception:
                pass
            product.delete()
            messages.success(request, f'商品「{product_name}」已彻底删除(含库存/流水/销售记录)')
        else:
            # 默认:停用(软删除,保留账目数据)
            product.is_active = False
            product.updated_at = timezone.now()
            product.save()
            messages.success(request, f'商品「{product_name}」已停用')
        return redirect('product_list')
    
    return render(request, 'inventory/product/product_confirm_delete.html', {
        'product': product
    })


@login_required
def batch_update_supplier(request):
    """按款号批量设置/修改该款所有色码的主供应商。"""
    from inventory.models import Supplier
    if request.method == 'POST':
        model_no = (request.POST.get('model_no') or '').strip()
        supplier_id = request.POST.get('supplier') or ''
        supplier = Supplier.objects.filter(id=supplier_id).first() if supplier_id else None
        if not model_no:
            messages.error(request, '缺少款号')
            return redirect('product_list')
        count = Product.objects.filter(model_no=model_no).update(supplier=supplier)
        messages.success(request, f'款号「{model_no}」的 {count} 个色码已设置供应商:{supplier.name if supplier else "(已清空)"}')
        return redirect('product_list')
    model_no = request.GET.get('model_no', '')
    products = Product.objects.filter(model_no=model_no) if model_no else []
    return render(request, 'inventory/product/batch_supplier_form.html', {
        'model_no': model_no,
        'products': products,
        'suppliers': Supplier.objects.filter(is_active=True),
    })


@login_required
def product_import(request):
    """导入商品视图"""
    if request.method == 'POST':
        form = ProductImportForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES['csv_file']
            
            # 验证CSV文件
            validation_result = validate_csv(csv_file,
                                            required_headers=['name', 'price'],
                                            expected_headers=['name', 'category', 'price', 'cost',
                                                            'barcode', 'model_no', 'color', 'size',
                                                            'specification', 'manufacturer', 'discount_price'])
            
            if not validation_result['valid']:
                messages.error(request, f"CSV文件验证失败: {validation_result['errors']}")
                return render(request, 'inventory/product/product_import.html', {'form': form})
            
            # 处理CSV文件
            try:
                result = product_service.import_products_from_csv(csv_file, request.user)
                
                messages.success(request, f"成功导入 {result['success']} 个商品. {result['skipped']} 个被跳过, {result['failed']} 个失败.")
                
                if result['failed_rows']:
                    error_messages = []
                    for row_num, error in result['failed_rows']:
                        error_messages.append(f"行 {row_num}: {error}")
                    
                    # 将错误消息限制在合理范围内
                    if len(error_messages) > 5:
                        error_messages = error_messages[:5] + [f"... 及其他 {len(error_messages) - 5} 个错误."]
                    
                    for error in error_messages:
                        messages.warning(request, error)
                
                return redirect('product_list')
            
            except Exception as e:
                messages.error(request, f"导入过程中发生错误: {str(e)}")
                return render(request, 'inventory/product/product_import.html', {'form': form})
    else:
        form = ProductImportForm()
    
    # 生成样例CSV数据
    sample_data = [
        ['name', 'category', 'price', 'cost', 'barcode', 'model_no', 'color', 'size', 'specification', 'discount_price'],
        ['示例板鞋A', '运动休闲', '399.00', '240.00', '6900000000001', 'SKU-BOARD-A', 'white', '41', '41码', '299.00'],
        ['示例板鞋A', '运动休闲', '399.00', '240.00', '6900000000002', 'SKU-BOARD-A', 'white', '42', '42码', '299.00'],
    ]
    
    # 创建内存中的CSV
    sample_csv = io.StringIO()
    writer = csv.writer(sample_csv)
    for row in sample_data:
        writer.writerow(row)
    
    sample_csv_content = sample_csv.getvalue()
    
    context = {
        'form': form,
        'sample_csv': sample_csv_content,
    }
    
    return render(request, 'inventory/product/product_import.html', context)


@login_required
def product_export(request):
    """导出商品视图"""
    # 获取筛选参数
    category_id = request.GET.get('category', '')
    status = request.GET.get('status', '')
    
    # 基本查询集
    products = Product.objects.select_related('category').all()
    
    # 应用筛选
    if category_id:
        products = products.filter(category_id=category_id)
    
    if status == 'active':
        products = products.filter(is_active=True)
    elif status == 'inactive':
        products = products.filter(is_active=False)
    
    # 创建CSV响应
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="products_export.csv"'
    
    # 写入CSV
    writer = csv.writer(response)
    writer.writerow(['ID', '名称', '分类', '款号', '售价', '成本价', '条码', '规格', '颜色', '尺码', '状态'])
    
    for product in products:
        writer.writerow([
            product.id,
            product.name,
            product.category.name if product.category else '',
            product.model_no or '',
            product.price,
            product.cost,
            product.barcode or '',
            product.specification or '',
            product.get_color_display() if product.color else '',
            product.get_size_display() if product.size else '',
            '启用' if product.is_active else '禁用',
        ])
    
    return response

# 添加别名函数以兼容旧的导入
def product_edit(request, pk):
    """
    product_update的别名函数，用于保持向后兼容性
    """
    return product_update(request, pk) 