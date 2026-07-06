"""
库存管理视图
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.db.models import Q, Sum, F
from django.contrib.contenttypes.models import ContentType
from django.views.decorators.cache import never_cache
from django.core.paginator import Paginator

from inventory.models import (
    Product, Inventory, InventoryTransaction,
    OperationLog, check_inventory,
    update_inventory, Category, Supplier
)
from inventory.forms import InventoryTransactionForm
from inventory.forms.inventory_forms import QuickScanProductForm


@login_required
@never_cache
def inventory_list(request):
    """库存列表视图"""
    # 获取筛选参数
    category_id = request.GET.get('category', '')
    color = request.GET.get('color', '')
    size = request.GET.get('size', '')
    search_query = request.GET.get('search', '')
    supplier_id = request.GET.get('supplier', '')

    # 基础查询
    from django.db.models import OuterRef, Subquery
    _last_in = InventoryTransaction.objects.filter(
        product=OuterRef('product'), transaction_type='IN'
    ).order_by('-created_at')
    inventory_items = Inventory.objects.select_related(
        'product', 'product__category', 'product__supplier'
    ).annotate(
        last_in_date=Subquery(_last_in.values('transaction_date')[:1]),
        last_in_time=Subquery(_last_in.values('created_at')[:1]),
    )
    
    # 应用筛选条件
    if category_id:
        inventory_items = inventory_items.filter(product__category_id=category_id)
    
    if color:
        inventory_items = inventory_items.filter(product__color=color)
    
    if size:
        inventory_items = inventory_items.filter(product__size=size)

    if supplier_id:
        inventory_items = inventory_items.filter(product__supplier_id=supplier_id)
    
    if search_query:
        inventory_items = inventory_items.filter(
            Q(product__name__icontains=search_query) |
            Q(product__barcode__icontains=search_query)
        )

    # 默认隐藏停用款(is_active=False);?show_inactive=1 可查看停用款
    show_inactive = request.GET.get('show_inactive', '') == '1'
    if not show_inactive:
        inventory_items = inventory_items.filter(product__is_active=True)

    # 获取所有分类
    categories = Category.objects.all()

    # 颜色/尺码下拉用"商品里实际存在的值"(去重),而非预设枚举 —— 颜色尺码是自由输入
    colors = list(Product.objects.exclude(color='').values_list('color', flat=True).distinct().order_by('color'))
    sizes = list(Product.objects.exclude(size='').values_list('size', flat=True).distinct().order_by('size'))

    # 按 model_no(款号)聚合成款组:款头信息 + 该款各色码(Inventory 记录)
    from collections import OrderedDict
    groups = OrderedDict()
    for inv in inventory_items:
        p = inv.product
        key = p.model_no.strip() if (p.model_no and p.model_no.strip()) else f'_nobar_{p.barcode}'
        g = groups.get(key)
        if g is None:
            g = {
                'key': key, 'model_no': p.model_no, 'name': p.name,
                'category': p.category, 'supplier': p.supplier, 'image': p.image,
                'total_stock': 0, 'low_count': 0, 'items': [],
            }
            groups[key] = g
        g['items'].append(inv)
        g['total_stock'] += inv.quantity
        if inv.is_low_stock:
            g['low_count'] += 1

    # 款级分页(每页 20 款,与商品页一致);先分页再查图片池,避免查全量款的图
    from inventory.utils.query_utils import paginate_queryset
    inventory_groups = list(groups.values())
    page_obj = paginate_queryset(inventory_groups, request.GET.get('page', 1), 20)

    # 只给当前页款组带图片池(列表缩略图点击可预览/切换该款所有图);批量查避免 N+1
    from inventory.models import ProductImage
    page_groups = list(page_obj.object_list)
    page_model_nos = {g['model_no'] for g in page_groups if g.get('model_no')}
    style_imgs = {}
    if page_model_nos:
        for pi in ProductImage.objects.filter(product__model_no__in=page_model_nos).select_related('product').order_by('order', 'id'):
            style_imgs.setdefault(pi.product.model_no, []).append(pi.image.url)
    for g in page_groups:
        if g.get('model_no'):
            g['images'] = style_imgs.get(g['model_no'], [])
        else:
            g['images'] = [g['image'].url] if g.get('image') else []

    context = {
        'page_obj': page_obj,
        'inventory_groups': page_groups,
        'categories': categories,
        'colors': colors,
        'sizes': sizes,
        'selected_category': category_id,
        'selected_color': color,
        'selected_size': size,
        'selected_supplier': supplier_id,
        'search_query': search_query,
        'show_inactive': show_inactive,
        'suppliers': Supplier.objects.filter(is_active=True),
    }

    # 入库后跳转:提示打印本次入库商品的条码贴纸
    just_in_id = request.GET.get('just_in', '')
    if just_in_id and just_in_id.isdigit():
        try:
            context['just_in_product'] = Product.objects.get(id=int(just_in_id))
        except Product.DoesNotExist:
            pass

    return render(request, 'inventory/inventory_list.html', context)


@login_required
def inventory_transaction_list(request):
    """库存交易记录列表，显示所有入库、出库和调整记录"""
    # 获取筛选参数
    transaction_type = request.GET.get('type', '')
    product_id = request.GET.get('product_id', '')
    supplier_id = request.GET.get('supplier', '')
    search_query = request.GET.get('search', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    
    # 基础查询
    transactions = InventoryTransaction.objects.select_related('product', 'operator', 'supplier').all()

    # 应用筛选条件
    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)

    if supplier_id:
        transactions = transactions.filter(supplier_id=supplier_id)
    
    if product_id:
        transactions = transactions.filter(product_id=product_id)

    # 按款号过滤(查该款所有色码的进出流水)
    model_no = request.GET.get('model_no', '')
    if model_no:
        transactions = transactions.filter(product__model_no=model_no)
    
    if search_query:
        transactions = transactions.filter(
            Q(product__name__icontains=search_query) | 
            Q(product__barcode__icontains=search_query) |
            Q(notes__icontains=search_query)
        )
    
    # 按业务日期筛选(transaction_date 优先;为空回退 created_at,和列表"业务日期"列一致)
    from datetime import datetime, timedelta
    if date_from:
        try:
            d = datetime.strptime(date_from, '%Y-%m-%d').date()
            transactions = transactions.filter(
                Q(transaction_date__gte=d) |
                (Q(transaction_date__isnull=True) & Q(created_at__date__gte=d))
            )
        except (ValueError, TypeError):
            pass

    if date_to:
        try:
            d = (datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)).date()  # +1 天以包含整天
            transactions = transactions.filter(
                Q(transaction_date__lt=d) |
                (Q(transaction_date__isnull=True) & Q(created_at__date__lt=d))
            )
        except (ValueError, TypeError):
            pass
    
    # 排序与筛选口径对齐:业务日期优先,为空回退操作时间
    from django.db.models import F
    transactions = transactions.order_by(F('transaction_date').desc(nulls_last=True), '-created_at')
    
    # 分页
    paginator = Paginator(transactions, 20)  # 每页20条记录
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    from inventory.models import Supplier
    return render(request, 'inventory/inventory_transaction_list.html', {
        'page_obj': page_obj,
        'transaction_type': transaction_type,
        'product_id': product_id,
        'supplier_id': supplier_id,
        'search_query': search_query,
        'date_from': date_from,
        'date_to': date_to,
        'model_no': model_no,
        'transaction_types': dict(InventoryTransaction.TRANSACTION_TYPES),
        'suppliers': Supplier.objects.all(),
    })


@login_required
@never_cache
def cash_flow(request):
    """资金流水(账本):把销售收入 / 会员充值 / 进货支出 三类钱流汇总成一本账。
    每笔都有金额和收支方向,顶部汇总本期收入、支出、净额。"""
    from inventory.models import Sale, RechargeRecord
    from datetime import datetime, timedelta, date as date_cls

    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    kind = request.GET.get('kind', '')  # sale / recharge / purchase / ''(全部)
    quick = request.GET.get('quick', '')  # today / week / month

    # 快捷区间
    today = date_cls.today()
    if quick == 'today':
        date_from = date_to = today.strftime('%Y-%m-%d')
    elif quick == 'week':
        date_from = (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')
    elif quick == 'month':
        date_from = today.replace(day=1).strftime('%Y-%m-%d')
        date_to = today.strftime('%Y-%m-%d')

    df, dt = None, None
    if date_from:
        try:
            df = datetime.strptime(date_from, '%Y-%m-%d').date()
        except ValueError:
            df = None
    if date_to:
        try:
            dt = datetime.strptime(date_to, '%Y-%m-%d').date()
        except ValueError:
            dt = None

    # 统一构建流水条目列表: (sort_key, 业务日期, 类型, 说明, 收入, 支出, 操作员, 关联对象)
    items = []

    def _date_ok(d):
        if d is None:
            return False
        d = d.date() if hasattr(d, 'date') else d
        if df and d < df:
            return False
        if dt and d > dt:
            return False
        return True

    # 1. 销售收入(钱进)
    if kind in ('', 'sale'):
        sales = Sale.objects.filter(status='COMPLETED').select_related('member', 'operator')
        for s in sales:
            d = s.created_at
            if not _date_ok(d):
                continue
            who = s.member.name if s.member else '散客'
            items.append({
                'when': d, 'biz_date': d.date(), 'kind': 'sale', 'kind_label': '销售',
                'desc': f'销售单 #{s.id} · {who}',
                'income': s.final_amount or s.total_amount or 0, 'expense': 0,
                'operator': s.operator.username if s.operator else '-',
            })

    # 2. 会员充值(钱进)
    if kind in ('', 'recharge'):
        for r in RechargeRecord.objects.select_related('member', 'operator'):
            d = r.created_at
            if not _date_ok(d):
                continue
            items.append({
                'when': d, 'biz_date': d.date(), 'kind': 'recharge', 'kind_label': '充值',
                'desc': f'会员充值 · {r.member.name if r.member else "-"}',
                'income': r.actual_amount or r.amount or 0, 'expense': 0,
                'operator': r.operator.username if r.operator else '-',
            })

    # 3. 进货支出(钱出)= 入库流水 × 商品成本
    if kind in ('', 'purchase'):
        for t in InventoryTransaction.objects.filter(
            transaction_type='IN'
        ).select_related('product', 'supplier', 'operator'):
            d = t.transaction_date or t.created_at.date()
            if not _date_ok(d):
                continue
            cost = (t.product.cost or 0) * t.quantity
            sup = t.supplier.name if t.supplier else '-'
            items.append({
                'when': t.created_at, 'biz_date': d if not hasattr(d, 'date') else d.date(),
                'kind': 'purchase', 'kind_label': '进货',
                'desc': f'进货 · {t.product.name} ×{t.quantity} · {sup}',
                'income': 0, 'expense': cost,
                'operator': t.operator.username if t.operator else '-',
            })

    # 倒序(最新在上)
    items.sort(key=lambda x: x['when'], reverse=True)

    # 汇总(基于全部筛选结果,非仅当前页)
    total_in = sum(x['income'] for x in items)
    total_out = sum(x['expense'] for x in items)
    net = total_in - total_out

    paginator = Paginator(items, 30)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'inventory/cash_flow.html', {
        'page_obj': page_obj,
        'total_in': total_in,
        'total_out': total_out,
        'net': net,
        'date_from': date_from,
        'date_to': date_to,
        'kind': kind,
        'quick': quick,
        'count': len(items),
    })


@login_required
def inventory_in(request):
    """入库视图"""
    if request.method == 'POST':
        form = InventoryTransactionForm(request.POST)
        if form.is_valid():
            product = form.cleaned_data['product']
            quantity = form.cleaned_data['quantity']
            notes = form.cleaned_data['notes']
            
            # 使用工具函数更新库存
            success, inventory, result = update_inventory(
                product=product,
                quantity=quantity,  # 正数表示入库
                transaction_type='IN',
                operator=request.user,
                notes=notes,
                supplier=form.cleaned_data.get('supplier'),
                transaction_date=form.cleaned_data.get('transaction_date')
            )
            
            if success:
                # 记录操作日志
                OperationLog.objects.create(
                    operator=request.user,
                    operation_type='INVENTORY',
                    details=f'入库: {product.name} x {quantity}',
                    related_object_id=inventory.id,
                    related_content_type=ContentType.objects.get_for_model(inventory)
                )

                messages.success(request, f'{product.name} 入库成功，当前库存: {inventory.quantity}')
                # 带本次入库商品 id 回库存页,供顶部"打印条码贴纸"按钮用
                return redirect(f'{reverse("inventory_list")}?just_in={product.id}')
            else:
                messages.error(request, f'入库失败: {result}')
    else:
        form = InventoryTransactionForm()
        product_id = request.GET.get('product_id')
        if product_id:
            try:
                form.fields['product'].initial = Product.objects.get(id=product_id)
            except Product.DoesNotExist:
                pass

    return render(request, 'inventory/inventory_transaction_form.html', {
        'form': form,
        'form_title': '商品入库',
        'submit_text': '确认入库',
        'transaction_type': 'IN'
    })


@login_required
def inventory_out(request):
    """出库视图"""
    if request.method == 'POST':
        form = InventoryTransactionForm(request.POST)
        if form.is_valid():
            product = form.cleaned_data['product']
            quantity = form.cleaned_data['quantity']
            notes = form.cleaned_data['notes']

            # 先检查库存是否足够
            if not check_inventory(product, quantity):
                messages.error(request, f'出库失败: {product.name} 当前库存不足')
                return render(request, 'inventory/inventory_transaction_form.html', {
                    'form': form,
                    'form_title': '商品出库',
                    'submit_text': '确认出库',
                    'transaction_type': 'OUT'
                })
            
            # 使用工具函数更新库存
            success, inventory, result = update_inventory(
                product=product,
                quantity=-quantity,  # 负数表示出库
                transaction_type='OUT',
                operator=request.user,
                notes=notes,
                transaction_date=form.cleaned_data.get('transaction_date')
            )
            
            if success:
                # 记录操作日志
                OperationLog.objects.create(
                    operator=request.user,
                    operation_type='INVENTORY',
                    details=f'出库: {product.name} x {quantity}',
                    related_object_id=inventory.id,
                    related_content_type=ContentType.objects.get_for_model(inventory)
                )

                print(f'OUT_POST success: 出库成功 {product.name} x{quantity} 当前库存={inventory.quantity}', flush=True)
                messages.success(request, f'{product.name} 出库成功，当前库存: {inventory.quantity}')
                # 重定向到库存页,禁止缓存
                resp = redirect('inventory_list')
                resp['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                resp['Pragma'] = 'no-cache'
                resp['Expires'] = '0'
                return resp
            else:
                messages.error(request, f'出库失败: {result}')
        else:
            messages.error(request, f'出库校验未通过,请检查数量')
    else:
        form = InventoryTransactionForm()
        product_id = request.GET.get('product_id')
        if product_id:
            try:
                form.fields['product'].initial = Product.objects.get(id=product_id)
            except Product.DoesNotExist:
                pass

    return render(request, 'inventory/inventory_transaction_form.html', {
        'form': form,
        'form_title': '商品出库',
        'submit_text': '确认出库',
        'transaction_type': 'OUT'
    })


@login_required
def inventory_adjust(request):
    """库存调整视图"""
    if request.method == 'POST':
        form = InventoryTransactionForm(request.POST)
        if form.is_valid():
            product = form.cleaned_data['product']
            quantity = form.cleaned_data['quantity']
            notes = form.cleaned_data['notes']
            
            # 获取当前库存
            try:
                inventory = Inventory.objects.get(product=product)
                current_quantity = inventory.quantity
            except Inventory.DoesNotExist:
                current_quantity = 0
            
            # 计算调整值
            adjustment_action = request.POST.get('adjustment_action')
            if adjustment_action == 'set':
                # 设置为指定数量
                if quantity < 0:
                    messages.error(request, '库存数量不能为负数')
                    return render(request, 'inventory/inventory_adjust_form.html', {
                        'form': form,
                        'current_quantity': current_quantity
                    })
                
                adjustment_value = quantity - current_quantity
            elif adjustment_action == 'add':
                # 增加指定数量
                adjustment_value = quantity
            elif adjustment_action == 'subtract':
                # 减少指定数量
                if quantity > current_quantity:
                    messages.error(request, f'减少的数量({quantity})超过了当前库存({current_quantity})')
                    return render(request, 'inventory/inventory_adjust_form.html', {
                        'form': form,
                        'current_quantity': current_quantity
                    })
                
                adjustment_value = -quantity
            else:
                messages.error(request, '请选择有效的调整方式')
                return render(request, 'inventory/inventory_adjust_form.html', {
                    'form': form,
                    'current_quantity': current_quantity
                })
            
            # 使用工具函数更新库存
            success, inventory, result = update_inventory(
                product=product,
                quantity=adjustment_value,
                transaction_type='ADJUST',
                operator=request.user,
                notes=f"{notes} (调整前: {current_quantity})",
                transaction_date=form.cleaned_data.get('transaction_date')
            )
            
            if success:
                # 记录操作日志
                OperationLog.objects.create(
                    operator=request.user,
                    operation_type='INVENTORY',
                    details=f'库存调整: {product.name} 从 {current_quantity} 到 {inventory.quantity}',
                    related_object_id=inventory.id,
                    related_content_type=ContentType.objects.get_for_model(inventory)
                )
                
                messages.success(request, f'{product.name} 库存调整成功，当前库存: {inventory.quantity}')
                return redirect('inventory_list')
            else:
                messages.error(request, f'库存调整失败: {result}')
    else:
        form = InventoryTransactionForm()
        product_id = request.GET.get('product_id')
        if product_id:
            try:
                product = Product.objects.get(id=product_id)
                form.fields['product'].initial = product
            except Product.DoesNotExist:
                pass
    
    # 获取当前库存（如果已选择商品）
    current_quantity = 0
    if form.initial.get('product'):
        try:
            inventory = Inventory.objects.get(product=form.initial['product'])
            current_quantity = inventory.quantity
        except Inventory.DoesNotExist:
            pass
    
    return render(request, 'inventory/inventory_adjust_form.html', {
        'form': form,
        'current_quantity': current_quantity
    })


@login_required
def inventory_transaction_create(request):
    """创建入库交易视图"""
    if request.method == 'POST':
        form = InventoryTransactionForm(request.POST)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.transaction_type = 'IN'
            transaction.operator = request.user
            transaction.save()
            
            inventory = Inventory.objects.get(product=transaction.product)
            inventory.quantity += transaction.quantity
            inventory.save()
            
            # 记录操作日志
            OperationLog.objects.create(
                operator=request.user,
                operation_type='INVENTORY',
                details=f'入库操作: {transaction.product.name}, 数量: {transaction.quantity}',
                related_object_id=transaction.id,
                related_content_type=ContentType.objects.get_for_model(InventoryTransaction)
            )
            
            messages.success(request, '入库操作成功')
            return redirect('inventory_list')
    else:
        form = InventoryTransactionForm()
    
    return render(request, 'inventory/inventory_form.html', {'form': form})


# ===== 扫码入库 / 出库 =====

def _scan_json(request):
    """从 JSON body 或 POST 取数据,兼容 fetch(JSON) 与表单提交。"""
    if request.content_type == 'application/json':
        import json
        try:
            return json.loads(request.body or b'{}')
        except ValueError:
            return {}
    return request.POST.dict()


def _parse_qty(data):
    """解析正整数数量,失败返回 None。"""
    try:
        q = int(data.get('quantity') or 1)
        return q if q > 0 else None
    except (TypeError, ValueError):
        return None


@login_required
def inventory_scan_in(request):
    """扫码入库:扫码 → 识别商品 → 按数量入库(整批/连续)。"""
    if request.method != 'POST':
        from inventory.forms.product_forms import category_optgroup_choices
        from inventory.models import Supplier
        return render(request, 'inventory/scan_in.html', {
            'title': '扫码入库',
            'category_choices': category_optgroup_choices(),
            'suppliers': Supplier.objects.filter(is_active=True),
        })

    data = _scan_json(request)
    barcode = (data.get('barcode') or '').strip()
    quantity = _parse_qty(data)
    if not barcode:
        return JsonResponse({'success': False, 'error': '条码不能为空'}, status=400)
    if quantity is None:
        return JsonResponse({'success': False, 'error': '数量必须是正整数'}, status=400)

    product = Product.objects.filter(Q(barcode=barcode) | Q(scan_code=barcode)).first()
    if not product:
        return JsonResponse({'success': False, 'unknown': True, 'barcode': barcode})

    sup = None
    if data.get('supplier'):
        from inventory.models import Supplier
        sup = Supplier.objects.filter(id=data.get('supplier')).first()
    success, inventory, result = update_inventory(
        product=product, quantity=quantity, transaction_type='IN',
        operator=request.user, notes=(data.get('notes') or '扫码入库').strip(), supplier=sup)
    if not success:
        return JsonResponse({'success': False, 'error': str(result)}, status=400)

    OperationLog.objects.create(
        operator=request.user, operation_type='INVENTORY',
        details=f'扫码入库: {product.name} x {quantity}',
        related_object_id=inventory.id,
        related_content_type=ContentType.objects.get_for_model(Inventory))
    return JsonResponse({
        'success': True, 'barcode': barcode, 'name': product.name,
        'model_no': product.model_no, 'quantity': quantity,
        'new_stock': inventory.quantity, 'low_stock': inventory.is_low_stock,
        'product_id': product.id})


@login_required
def inventory_scan_out(request):
    """扫码出库:扫码 → 识别商品 → 直接扣库存(内部领用/报损,不走销售单)。"""
    if request.method != 'POST':
        return render(request, 'inventory/scan_out.html', {'title': '扫码出库'})

    data = _scan_json(request)
    barcode = (data.get('barcode') or '').strip()
    quantity = _parse_qty(data)
    if not barcode:
        return JsonResponse({'success': False, 'error': '条码不能为空'}, status=400)
    if quantity is None:
        return JsonResponse({'success': False, 'error': '数量必须是正整数'}, status=400)

    product = Product.objects.filter(Q(barcode=barcode) | Q(scan_code=barcode)).first()
    if not product:
        return JsonResponse({'success': False, 'unknown': True, 'barcode': barcode})

    try:
        current = Inventory.objects.get(product=product).quantity
    except Inventory.DoesNotExist:
        current = 0
    if not check_inventory(product, quantity):
        return JsonResponse({
            'success': False, 'insufficient': True, 'name': product.name,
            'stock': current, 'requested': quantity})

    success, inventory, result = update_inventory(
        product=product, quantity=-quantity, transaction_type='OUT',
        operator=request.user, notes=(data.get('notes') or '扫码出库').strip())
    if not success:
        return JsonResponse({'success': False, 'error': str(result)}, status=400)

    OperationLog.objects.create(
        operator=request.user, operation_type='INVENTORY',
        details=f'扫码出库: {product.name} x {quantity}',
        related_object_id=inventory.id,
        related_content_type=ContentType.objects.get_for_model(Inventory))
    return JsonResponse({
        'success': True, 'barcode': barcode, 'name': product.name,
        'quantity': quantity, 'new_stock': inventory.quantity,
        'low_stock': inventory.is_low_stock})


@login_required
def scan_quick_create(request):
    """就地快速建档 + 入库:扫到未知条码,填关键字段建档同时入库。"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '仅支持 POST'}, status=405)

    data = _scan_json(request)
    quantity = _parse_qty(data)
    if quantity is None:
        return JsonResponse({'success': False, 'error': '数量必须是正整数'}, status=400)

    form = QuickScanProductForm(data)
    if not form.is_valid():
        return JsonResponse({'success': False, 'errors': form.errors.get_json_data()}, status=400)

    product = form.save()  # 创建商品档案(is_active 默认 True)
    # 款若已有图,同步到新 SKU(款图共享),避免列表/销售漏图
    try:
        from inventory.views.product import _sync_style_main_image
        _sync_style_main_image(product)
    except Exception:
        pass
    sup = None
    if data.get('supplier'):
        from inventory.models import Supplier
        sup = Supplier.objects.filter(id=data.get('supplier')).first()
        if sup:
            product.supplier = sup
            product.save(update_fields=['supplier'])
    success, inventory, result = update_inventory(
        product=product, quantity=quantity, transaction_type='IN',
        operator=request.user, notes='扫码快速建档入库', supplier=sup)
    if not success:
        return JsonResponse({'success': False, 'error': str(result)}, status=400)

    OperationLog.objects.create(
        operator=request.user, operation_type='INVENTORY',
        details=f'扫码建档入库: {product.name} x {quantity}',
        related_object_id=inventory.id,
        related_content_type=ContentType.objects.get_for_model(Inventory))
    return JsonResponse({
        'success': True, 'barcode': product.barcode, 'name': product.name,
        'model_no': product.model_no, 'quantity': quantity,
        'new_stock': inventory.quantity, 'product_id': product.id})


# ===== 截图 AI 识别进货单 + 批量录入 =====

def _call_dify_receipt(image_file):
    """调 Dify「单据识别」工作流,返回 (direction, items, 错误信息)。
    direction: 'in'(进货)/ 'out'(退货),由 Dify prompt 据单据标题/数量正负判断。"""
    import json as _json
    import re
    import requests
    from django.conf import settings

    base = getattr(settings, 'DIFY_BASE_URL', '').rstrip('/')
    key = getattr(settings, 'DIFY_RECEIPT_API_KEY', '').strip()
    if not base or not key:
        return None, None, None, 'Dify 未配置(请在 .env 填 DIFY_BASE_URL 和 DIFY_RECEIPT_API_KEY)'

    headers = {'Authorization': f'Bearer {key}'}

    # 1. 上传图到 Dify
    image_file.seek(0)
    try:
        files = {'file': (image_file.name, image_file.read(), image_file.content_type or 'image/png')}
        r = requests.post(f"{base}/v1/files/upload", headers=headers, files=files,
                          data={'user': 'ioe-receipt'}, timeout=60)
        r.raise_for_status()
        transfer_id = r.json().get('id')
        if not transfer_id:
            return None, None, None, f'Dify 上传图未返回 id: {r.text[:200]}'
    except Exception as e:
        return None, None, None, f'上传图到 Dify 失败: {e}'

    # 2. 运行工作流(blocking)——新版 Dify 文件变量放 inputs 里
    payload = {
        'inputs': {
            'image': {
                'transfer_method': 'local_file',
                'upload_file_id': transfer_id,
                'type': 'image',
            }
        },
        'response_mode': 'blocking',
        'user': 'ioe-receipt',
    }
    try:
        r = requests.post(f"{base}/v1/workflows/run",
                          headers={**headers, 'Content-Type': 'application/json'},
                          json=payload, timeout=180)
        r.raise_for_status()
        data = r.json()
        text = (data.get('data', {}).get('outputs', {}) or {}).get('text', '')
    except Exception as e:
        return None, None, None, f'调用 Dify 工作流失败: {e}'

    # 3. 解析 JSON(容错:剥离 markdown 代码块;兼容 {direction,items} 对象与 [items] 数组两种返回)
    text = (text or '').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    parsed = None
    try:
        parsed = _json.loads(text)
    except Exception:
        m = re.search(r'(\{.*\}|\[.*\])', text, re.S)
        if m:
            try:
                parsed = _json.loads(m.group())
            except Exception:
                pass
    direction = 'in'
    purchase_date = ''
    items = None
    if isinstance(parsed, dict):
        d = str(parsed.get('direction') or parsed.get('type') or 'in').strip().lower()
        direction = 'out' if d in ('out', 'return', '退货', '退货单', 'ref') else 'in'
        purchase_date = str(parsed.get('purchase_date') or parsed.get('date') or parsed.get('order_date') or '').strip()
        items = parsed.get('items') or parsed.get('goods') or parsed.get('products')
    elif isinstance(parsed, list):
        items = parsed
    if not isinstance(items, list):
        return None, None, None, f'Dify 返回非 JSON: {text[:200]}'
    return direction, purchase_date, items, None


@login_required
def receipt_recognize(request):
    """上传进货/退货单截图 → 调 Dify 识别方向+明细 → 预填批量录入表单。"""
    if request.method == 'POST' and request.FILES.get('image'):
        direction, purchase_date, items, err = _call_dify_receipt(request.FILES['image'])
        if err or items is None:
            messages.error(request, f'识别失败:{err or "未识别到商品"}')
            return render(request, 'inventory/upload_receipt.html', {})
        # 类目 code → id 映射(AI 据商品名判断返回 category_l1/l2 code,这里转成表单要的 id)
        cat_map = {c.code: c.id for c in Category.objects.all()}
        initial = [{
            'model_no': str(it.get('model_no', '') or ''),
            'name': str(it.get('name', '') or ''),
            'size': str(it.get('size', '') or ''),
            'color': str(it.get('color', '') or ''),
            'quantity': it.get('quantity', '') or '',
            'cost': it.get('price', '') or '',
            'category': cat_map.get(it.get('category_l1')) or '',
        } for it in items if it.get('name')]
        from inventory.forms.inventory_forms import BatchPurchaseFormSet
        from inventory.models import Supplier
        formset = BatchPurchaseFormSet(initial=initial)
        tip = '退货单(将出库 −,退给供应商)' if direction == 'out' else '进货单(将入库 +)'
        messages.success(request, f'AI 识别为{tip},共 {len(initial)} 款。单据价格已预填到「成本」,请补「售价」和「鞋类目」后提交。')
        return render(request, 'inventory/batch_purchase_form.html',
                      {'formset': formset, 'from_ai': True, 'recognized_count': len(initial),
                       'direction': direction, 'purchase_date': purchase_date,
                       'suppliers': Supplier.objects.filter(is_active=True)})
    return render(request, 'inventory/upload_receipt.html', {})


@login_required
def batch_purchase_create(request):
    """批量录入:进货 → 建档 + 入库(IN);退货 → 按款号+尺码+颜色匹配现有商品出库(OUT,退给供应商)。
    方向由表单隐藏字段 direction 决定('in'/'out'),默认 in。"""
    from inventory.forms.inventory_forms import BatchPurchaseFormSet
    from inventory.models import Supplier
    direction = (request.POST.get('direction') or 'in').strip().lower()
    if direction not in ('in', 'out'):
        direction = 'in'
    supplier = Supplier.objects.filter(id=request.POST.get('supplier') or 0).first()
    purchase_date = None
    _pds = request.POST.get('purchase_date') or ''
    if _pds:
        from datetime import datetime as _dt
        try:
            purchase_date = _dt.strptime(_pds, '%Y-%m-%d').date()
        except ValueError:
            purchase_date = None
    if request.method == 'POST':
        formset = BatchPurchaseFormSet(request.POST)
        try:
            _total = int(request.POST.get('form-TOTAL_FORMS') or 0)
        except ValueError:
            _total = 0
        _names = [request.POST.get(f'form-{i}-name') for i in range(_total)]
        _qtys = [request.POST.get(f'form-{i}-quantity') for i in range(_total)]
        print('BATCH_POST dir=', direction, 'INITIAL=', request.POST.get('form-INITIAL_FORMS'),
              'TOTAL=', _total, 'names=', _names, 'qtys=', _qtys, flush=True)
        if formset.is_valid():
            print('BATCH formset VALID, 开始建档', flush=True)
            created = stocked = 0
            skipped = []
            uncat = []
            noprice = []
            for i, f in enumerate(formset):
                cd = f.cleaned_data
                if not cd.get('name') or not cd.get('quantity'):
                    continue  # 空行跳过
                model_no = (cd.get('model_no') or '').strip()
                size = cd.get('size') or ''
                color = cd.get('color') or ''
                base = model_no or cd['name']
                barcode = f"{base}-{size}-{color}".strip('-') or f"{base}-{i}"
                qty = int(cd['quantity'])

                if direction == 'out':
                    # 退货:产品必须已在库(退给供应商不建档);库存不足拦截
                    product = Product.objects.filter(Q(barcode=barcode) | Q(scan_code=barcode)).first()
                    if not product:
                        skipped.append(f'{cd["name"]}({barcode}) 无档案')
                        continue
                    if not check_inventory(product, qty):
                        try:
                            cur = Inventory.objects.get(product=product).quantity
                        except Inventory.DoesNotExist:
                            cur = 0
                        skipped.append(f'{product.name} 库存不足(现 {cur},要退 {qty})')
                        continue
                    success, inv, result = update_inventory(
                        product, -qty, 'OUT', request.user, '退货出库(批量)',
                        supplier=supplier, transaction_date=purchase_date)
                    if success:
                        stocked += qty
                    else:
                        skipped.append(f'{product.name}: {result}')
                else:
                    # 进货:新款建档 + 入库;同款补货加库存
                    category = Category.objects.filter(id=cd['category']).first() if cd.get('category') else None
                    if category is None:
                        # 漏填鞋类目兜底:暂归首个分类,避免 not-null 崩,事后提示补正
                        category = Category.objects.first()
                        uncat.append(cd['name'])
                    cost = cd.get('cost') if cd.get('cost') is not None else None
                    price = cd.get('price') or None
                    discount_price = cd.get('discount_price') or None
                    if price is None:
                        # 售价未填:用成本兜底(避免 0),事后提示补售价
                        price = cost if cost is not None else 0
                        if cost is not None:
                            noprice.append(cd['name'])
                    if cost is None:
                        cost = price
                    product, was_created = Product.objects.get_or_create(
                        barcode=barcode,
                        defaults={'name': cd['name'], 'model_no': model_no, 'category': category,
                                  'price': price, 'discount_price': discount_price, 'cost': cost,
                                  'size': size, 'color': color,
                                  'supplier': supplier, 'is_active': True})
                    # 款若已有图,同步到本 SKU(款图共享)
                    try:
                        from inventory.views.product import _sync_style_main_image
                        _sync_style_main_image(product)
                    except Exception:
                        pass
                    if not was_created and supplier:
                        # 已有商品:用本次供应商更新主供应商
                        product.supplier = supplier
                        product.save(update_fields=['supplier'])
                    success, inv, result = update_inventory(
                        product, qty, 'IN', request.user, '批量进货录入',
                        supplier=supplier, transaction_date=purchase_date)
                    if was_created:
                        created += 1
                    if success:
                        stocked += qty
            if direction == 'out':
                msg = f'退货出库完成:共退 {stocked} 件'
                if skipped:
                    msg += f';跳过 {len(skipped)} 行 — ' + '; '.join(skipped)
                    messages.warning(request, msg)
                else:
                    messages.success(request, msg)
            else:
                msg = f'批量录入完成:新建 {created} 款,共入库 {stocked} 件'
                if uncat or noprice:
                    fallback = Category.objects.first()
                    parts = []
                    if uncat:
                        parts.append(f'{len(uncat)} 款未填鞋类目(已暂归「{fallback.name if fallback else "默认"}」)')
                    if noprice:
                        parts.append(f'{len(noprice)} 款未填售价(暂用成本)')
                    msg += ';' + '、'.join(parts) + ',请到商品管理补正'
                    messages.warning(request, msg)
                else:
                    messages.success(request, msg)
            return redirect('inventory_list')
        else:
            print('BATCH formset INVALID:', [dict(f.errors) for f in formset if f.errors],
                  'non_form:', formset.non_form_errors(), flush=True)
            _errs = []
            for i, f in enumerate(formset):
                if f.errors:
                    _errs.append(f'第{i+1}行 ' + '; '.join(str(k) for k in f.errors))
            if formset.non_form_errors():
                _errs.append(' '.join(str(e) for e in formset.non_form_errors()))
            messages.error(request, '录入校验未通过:' + (' | '.join(_errs) if _errs else '请检查数量/价格,或刷新页面重试'))
    else:
        formset = BatchPurchaseFormSet()
    return render(request, 'inventory/batch_purchase_form.html',
                  {'formset': formset, 'direction': direction, 'purchase_date': _pds,
                   'suppliers': Supplier.objects.filter(is_active=True)}) 