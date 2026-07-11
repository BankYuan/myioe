import re
from django import forms
from django.forms import inlineformset_factory
from django.db.models import F
from inventory.models import Product, Category, ProductImage, ProductBatch, Supplier


def category_choices():
    """鞋类目选项(只保留 8 个一级),返回 [(pk, name), ...] 平铺列表供下拉选择。

    第一项为空占位;二级类目已废弃,如需细分请用款号/标签。
    """
    l1s = Category.objects.filter(code=F('l1_code')).exclude(code='').order_by('id')
    choices = [('', '--- 请选择分类 ---')]
    choices += [(l1.pk, l1.name) for l1 in l1s]
    orphans = Category.objects.filter(code='')
    if orphans.exists():
        choices += [(c.pk, f'{c.name}(未分类)') for c in orphans.order_by('id')]
    return choices


# 兼容旧调用名(views/forms 多处仍引用 category_optgroup_choices)
category_optgroup_choices = category_choices


class ProductForm(forms.ModelForm):
    barcode = forms.CharField(
        max_length=100,
        label='商品条码',
        help_text='支持EAN-13、UPC、ISBN等标准条码格式',
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': '请输入商品条码',
            'autocomplete': 'off',  # 防止自动填充
            'inputmode': 'numeric',  # 在移动设备上显示数字键盘
            'pattern': '[A-Za-z0-9-]+',  # HTML5验证模式，修复转义序列
            'aria-label': '商品条码'
        })
    )
    
    # 添加库存预警级别字段
    warning_level = forms.IntegerField(
        label='预警库存',
        help_text='库存低于此数量时将发出预警',
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '0',
            'step': '1',
            'placeholder': '预警数量',
            'aria-label': '预警库存'
        })
    )

    # 颜色/尺码自由输入(鞋类颜色尺码多变,不限于预设;和批量录入一致)
    color = forms.CharField(
        label='颜色', required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '可输入或选择', 'aria-label': '颜色', 'list': 'id_color_options'})
    )
    size = forms.CharField(
        label='尺码', required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '可输入或选择', 'aria-label': '尺码', 'list': 'id_size_options'})
    )

    class Meta:
        model = Product
        fields = ['barcode', 'scan_code', 'model_no', 'name', 'category', 'supplier', 'color', 'size', 'price', 'discount_price', 'cost', 'image', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '请输入商品名称', 'aria-label': '商品名称'}),
            'model_no': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '款号(同款共享)', 'aria-label': '款号'}),
            'scan_code': forms.TextInput(attrs={'class': 'form-control', 'readonly': True, 'aria-label': '扫码码(贴纸条码,EAN-13自动生成)'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '售价', 'inputmode': 'decimal', 'aria-label': '售价'}),
            'discount_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '折后价(可选)', 'inputmode': 'decimal', 'aria-label': '折后价'}),
            'cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '成本价', 'inputmode': 'decimal', 'aria-label': '成本价'}),
            'category': forms.Select(attrs={'class': 'form-control form-select', 'aria-label': '商品分类'}),
            'supplier': forms.Select(attrs={'class': 'form-control form-select', 'aria-label': '供应商'}),
            'image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*', 'aria-label': '商品图片'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'aria-label': '是否启用'}),
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 分类下拉按一级鞋类目分组(optgroup),一级与二级类目都可选
        self.fields['category'].widget.choices = category_optgroup_choices()

    def clean_barcode(self):
        barcode = self.cleaned_data.get('barcode')
        if barcode:
            # 移除空格和其他不可见字符
            barcode = re.sub(r'\s', '', barcode).strip()
            
            # 检查是否只包含数字、字母和连字符
            if not all(c.isalnum() or c == '-' for c in barcode):
                raise forms.ValidationError('条码只能包含数字、字母和连字符')
            
            # 检查条码是否已存在（排除当前实例）
            existing = Product.objects.filter(barcode=barcode)
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
                
            if existing.exists():
                raise forms.ValidationError('该条码已存在，请勿重复添加')
                
            # 检查常见条码格式
            # 标准条码格式
            # EAN-13: 13位数字
            # EAN-8: 8位数字
            # UPC-A: 12位数字
            # UPC-E: 8位数字，以0开头
            # ISBN-13: 13位数字，通常以978或979开头
            # ISBN-10: 10位数字或数字+X
            # JAN: 日本商品编码，13位数字，以45或49开头
            # ITF-14: 14位数字，通常用于物流包装
            # GTIN-14: 14位数字，全球贸易项目代码
            # Code-39: 可变长度，字母数字和特定符号
            # Code-128: 可变长度，所有ASCII字符
            ean13_pattern = re.compile(r'^\d{13}$')
            ean8_pattern = re.compile(r'^\d{8}$')
            upc_pattern = re.compile(r'^\d{12}$')
            upc_e_pattern = re.compile(r'^0\d{7}$')
            isbn13_pattern = re.compile(r'^(978|979)\d{10}$')
            isbn10_pattern = re.compile(r'^\d{9}[\dX]$')
            jan_pattern = re.compile(r'^(45|49)\d{11}$')
            itf14_pattern = re.compile(r'^\d{14}$')
            gtin14_pattern = re.compile(r'^\d{14}$')
            
            # 如果不符合任何标准格式，添加警告（但不阻止保存）
            is_standard_format = (
                ean13_pattern.match(barcode) or
                ean8_pattern.match(barcode) or
                upc_pattern.match(barcode) or
                upc_e_pattern.match(barcode) or
                isbn13_pattern.match(barcode) or
                isbn10_pattern.match(barcode) or
                jan_pattern.match(barcode) or
                itf14_pattern.match(barcode) or
                gtin14_pattern.match(barcode)
            )
            
            if not is_standard_format:
                # 添加警告，但不阻止保存
                self.add_warning = '条码格式不符合常见标准格式，请确认无误'
                
        return barcode
        
    def clean(self):
        cleaned_data = super().clean()
        price = cleaned_data.get('price')
        cost = cleaned_data.get('cost')
        
        if price is not None and cost is not None and price < cost:
            self.add_warning = '当前售价低于成本价，请确认无误'
            
        return cleaned_data


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'code', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '分类名称',
                'aria-label': '分类名称',
                'style': 'height: 48px; font-size: 16px;',
                'autocomplete': 'off',  # 防止自动填充
                'autofocus': True  # 自动获取焦点
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '类目编码(英文,如 sneakers);填了才进商品下拉',
                'aria-label': '类目编码',
                'style': 'height: 48px; font-size: 16px;'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': '分类描述',
                'rows': 3,
                'aria-label': '分类描述',
                'style': 'font-size: 16px;'  # 增大字体
            }),
        }

    def save(self, commit=True):
        category = super().save(commit=False)
        # 有编码 = 一级类目(l1_code 与 code 一致,才会出现在商品分类下拉里)
        if category.code:
            category.code = category.code.strip()
            category.l1_code = category.code
        if commit:
            category.save()
        return category
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 添加响应式布局的辅助类
        for field in self.fields.values():
            field.widget.attrs.update({
                'class': field.widget.attrs.get('class', '') + ' mb-2',  # 添加下边距
                'autocapitalize': 'off',  # 防止自动大写首字母
            })
    
    def clean_name(self):
        name = self.cleaned_data.get('name')
        if name:
            # 移除多余的空格
            name = name.strip()
            
            # 检查名称长度
            if len(name) < 2:
                raise forms.ValidationError('分类名称至少需要2个字符')
                
            # 检查是否已存在相同名称的分类（排除当前实例）
            existing = Category.objects.filter(name=name)
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
                
            if existing.exists():
                raise forms.ValidationError('该分类名称已存在，请使用其他名称')
                
        return name 


class ProductBatchForm(forms.ModelForm):
    """商品批次表单"""
    class Meta:
        model = ProductBatch
        fields = ['batch_number', 'production_date', 'expiry_date', 'quantity', 'cost_price', 'supplier', 'remarks']
        widgets = {
            'batch_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '批次号',
                'aria-label': '批次号'
            }),
            'production_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'aria-label': '生产日期'
            }),
            'expiry_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'aria-label': '过期日期'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '1',
                'placeholder': '数量',
                'aria-label': '数量'
            }),
            'cost_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': '成本价',
                'aria-label': '成本价'
            }),
            'supplier': forms.Select(attrs={
                'class': 'form-control form-select',
                'aria-label': '供应商'
            }),
            'remarks': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': '备注',
                'aria-label': '备注'
            }),
        }

    def clean_quantity(self):
        quantity = self.cleaned_data.get('quantity')
        if quantity is not None and quantity < 0:
            raise forms.ValidationError('数量不能为负数')
        return quantity

    def clean_cost_price(self):
        cost_price = self.cleaned_data.get('cost_price')
        if cost_price is not None and cost_price < 0:
            raise forms.ValidationError('成本价不能为负数')
        return cost_price


class ProductImageForm(forms.ModelForm):
    """商品图片表单(供 ProductImageFormSet 用)。新图 image_type 默认主图,避免忘选导致必填校验失败、整组图片不保存。"""
    class Meta:
        model = ProductImage
        fields = ('image', 'image_type', 'alt_text', 'is_primary')
        widgets = {
            'image': forms.FileInput(attrs={'class': 'form-control img-input', 'accept': 'image/*', 'aria-label': '图片'}),
            'image_type': forms.Select(attrs={'class': 'form-control form-select', 'aria-label': '图片类型'}),
            'alt_text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '图片描述', 'aria-label': '图片描述'}),
            'is_primary': forms.CheckboxInput(attrs={'class': 'form-check-input', 'aria-label': '是否主图'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # image/image_type 不强制必填:5 个上传位里没选文件的空行不应让整组校验失败
        # (image_type 下拉 HTML 默认选第一项「白底主图」;order 已从表单移除,用模型默认 0)
        self.fields['image'].required = False
        self.fields['image_type'].required = False


# 创建商品图片的内联表单集
ProductImageFormSet = inlineformset_factory(
    Product,
    ProductImage,
    form=ProductImageForm,
    extra=0,  # 不显示空行;新图走批量上传(bulk_images),formset 只管已传图的类型/删除
    can_delete=True,
)


class ProductImportForm(forms.Form):
    """商品导入表单"""
    csv_file = forms.FileField(
        label='CSV文件',
        required=True,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv',
            'aria-label': 'CSV文件'
        })
    )
    
    def clean_csv_file(self):
        csv_file = self.cleaned_data.get('csv_file')
        if csv_file:
            # 检查文件类型
            if not csv_file.name.endswith('.csv'):
                raise forms.ValidationError('请上传CSV格式的文件')
            
            # 检查文件大小，限制为5MB
            if csv_file.size > 5 * 1024 * 1024:
                raise forms.ValidationError('文件大小不能超过5MB')
        
        return csv_file 