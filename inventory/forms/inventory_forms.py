from django import forms

from inventory.models import InventoryTransaction, Product, Supplier


class InventoryTransactionForm(forms.ModelForm):
    class Meta:
        model = InventoryTransaction
        fields = ['product', 'quantity', 'transaction_date', 'notes', 'supplier']
        widgets = {
            'product': forms.Select(attrs={
                'class': 'form-control form-select',
                'aria-label': '商品',
                'style': 'height: 48px; font-size: 16px;'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'step': '1',
                'placeholder': '数量',
                'inputmode': 'numeric',  # 在移动设备上显示数字键盘
                'aria-label': '数量',
                'autocomplete': 'off',  # 防止自动填充
                'pattern': '[0-9]*',  # HTML5验证，只允许数字
                'style': 'height: 48px; font-size: 16px;'
            }),
            'transaction_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'aria-label': '业务日期(拿货/操作日期,可选)'
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control',
                'placeholder': '备注信息',
                'aria-label': '备注'
            }),
            'supplier': forms.Select(attrs={
                'class': 'form-control form-select',
                'aria-label': '供应商'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 使用select_related优化查询
        self.fields['product'].queryset = Product.objects.all().select_related('category')
        self.fields['supplier'].queryset = Supplier.objects.all()
        self.fields['supplier'].required = False
        
        # 添加响应式布局的辅助类
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': field.widget.attrs.get('class', '') + ' mb-2',  # 添加下边距
            })
    
    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity is not None and quantity <= 0:
            raise forms.ValidationError('数量必须大于0')
        return quantity


class QuickScanProductForm(forms.ModelForm):
    """扫码入库时,扫到未知条码就地快速建档用的精简表单。"""

    class Meta:
        model = Product
        fields = ['barcode', 'name', 'model_no', 'category', 'price', 'cost']
        widgets = {
            'barcode': forms.TextInput(attrs={'class': 'form-control', 'readonly': True}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '商品名称'}),
            'model_no': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '款号(同款共享)'}),
            'category': forms.Select(attrs={'class': 'form-control form-select'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '售价'}),
            'cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '成本价'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from inventory.forms.product_forms import category_optgroup_choices
        self.fields['category'].widget.choices = category_optgroup_choices()
        self.fields['category'].required = True


class BatchPurchaseItemForm(forms.Form):
    """批量进货录入的一行(可被 AI 识别结果预填)。"""
    model_no = forms.CharField(label='款号', required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '款号'}))
    name = forms.CharField(label='商品名', required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '商品名'}))
    category = forms.ChoiceField(label='鞋类目', required=False, widget=forms.Select(attrs={'class': 'form-control form-select'}))
    size = forms.CharField(label='尺码', required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '尺码'}))
    color = forms.CharField(label='颜色', required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '颜色'}))
    price = forms.DecimalField(label='售价', required=False, decimal_places=2, widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '售价'}))
    cost = forms.DecimalField(label='成本', required=False, decimal_places=2, widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '成本'}))
    quantity = forms.IntegerField(label='数量', required=False, min_value=1, widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '数量'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from inventory.forms.product_forms import category_optgroup_choices
        self.fields['category'].choices = category_optgroup_choices()


BatchPurchaseFormSet = forms.formset_factory(BatchPurchaseItemForm, extra=10)


class SupplierForm(forms.ModelForm):
    """供应商档案表单。"""

    class Meta:
        model = Supplier
        fields = ['name', 'contact_person', 'phone', 'address', 'remarks', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '供应商名称(如 欧乐琳)'}),
            'contact_person': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '联系人'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '联系电话'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': '地址'}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': '备注(结算方式/账期等)'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        } 