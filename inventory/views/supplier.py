from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q

from inventory.models import Supplier
from inventory.forms.inventory_forms import SupplierForm


@login_required
def supplier_list(request):
    """供应商列表"""
    search = (request.GET.get('search') or '').strip()
    qs = Supplier.objects.all()
    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(contact_person__icontains=search) |
            Q(phone__icontains=search)
        )
    qs = qs.annotate(product_count=Count('products')).order_by('-is_active', 'name')
    return render(request, 'inventory/supplier_list.html', {
        'suppliers': qs,
        'search_query': search,
    })


@login_required
def supplier_create(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            supplier = form.save()
            messages.success(request, f'供应商「{supplier.name}」已创建')
            return redirect('supplier_list')
    else:
        form = SupplierForm()
    return render(request, 'inventory/supplier_form.html', {
        'form': form, 'title': '新增供应商', 'submit_text': '创建',
    })


@login_required
def supplier_update(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            supplier = form.save()
            messages.success(request, f'供应商「{supplier.name}」已更新')
            return redirect('supplier_list')
    else:
        form = SupplierForm(instance=supplier)
    return render(request, 'inventory/supplier_form.html', {
        'form': form, 'title': '编辑供应商', 'submit_text': '保存',
    })


@login_required
def supplier_delete(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        name = supplier.name
        # Supplier 的 FK 都是 SET_NULL,删除安全(商品/流水供应商字段置空)
        supplier.delete()
        messages.success(request, f'供应商「{name}」已删除')
        return redirect('supplier_list')
    return render(request, 'inventory/supplier_confirm_delete.html', {
        'supplier': supplier,
    })
