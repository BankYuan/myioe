import os
import re

from django.db import models
from django.core.exceptions import ValidationError


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name='分类名称')
    code = models.CharField(
        max_length=64, blank=True, default='', db_index=True,
        verbose_name='类目编码',
        help_text='对应内容平台鞋类目的标准编码(如 sneakers)'
    )
    l1_code = models.CharField(
        max_length=64, blank=True, default='', db_index=True,
        verbose_name='一级类目编码',
        help_text='所属一级类目编码;一级类目自身则与 code 相同'
    )
    description = models.TextField(blank=True, verbose_name='分类描述')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        verbose_name = '商品分类'
        verbose_name_plural = '商品分类'
    
    def __str__(self):
        return self.name


def _ean13_checksum(twelve):
    """计算 EAN-13 校验位(输入前12位数字字符串)。"""
    total = 0
    for i, c in enumerate(twelve):
        d = int(c)
        total += d if i % 2 == 0 else d * 3
    return (10 - total % 10) % 10


def _gen_scan_code():
    """生成合法 EAN-13(69开头 + 10位随机 + 校验位 = 13位)。
    第13位必须是正确校验位,否则 JsBarcode 的 EAN13 渲染会报错、画不出条码。"""
    import random
    while True:
        twelve = '69' + ''.join(str(random.randint(0, 9)) for _ in range(10))
        code = twelve + str(_ean13_checksum(twelve))
        if not Product.objects.filter(scan_code=code).exists():
            return code


def product_image_path(instance, filename):
    """商品图片在 MinIO 的存储路径:products/{款号}/{图片类型}_{序号}.{扩展名}

    按款号(model_no)分目录,MinIO 控制台里同款图聚在一起,一眼认出是哪款鞋;
    文件名含图片类型(main/side/sole/detail/on_foot)+ 该款该类型下的递增序号,避免重名。
    款号为空或含非法字符时归到 _unsorted/。

    instance 可能是 ProductImage(带 .product)或 Product(自身)。
    """
    product = getattr(instance, 'product', None) or instance
    model_no = (getattr(product, 'model_no', '') or '').strip()
    image_type = getattr(instance, 'image_type', '') or 'main'
    ext = os.path.splitext(filename)[1].lower() or '.jpg'

    # 目录名只保留字母/数字/横线,其余(空格、斜杠、中文等)替换成 _,避免破坏 S3 路径
    folder = re.sub(r'[^a-zA-Z0-9\-]', '_', model_no).strip('_') or '_unsorted'

    # 该款该类型已有图片数 +1 作为序号(同款多张主图 main_01/02/... 不重名)
    if model_no:
        seq = ProductImage.objects.filter(
            product__model_no=model_no, image_type=image_type
        ).count() + 1
    else:
        seq = ProductImage.objects.filter(
            product=product, image_type=image_type
        ).count() + 1

    return f'products/{folder}/{image_type}_{seq:02d}{ext}'


class Product(models.Model):
    COLOR_CHOICES = [
        ('', '无颜色'),
        ('black', '黑色'),
        ('white', '白色'),
        ('red', '红色'),
        ('blue', '蓝色'),
        ('green', '绿色'),
        ('yellow', '黄色'),
        ('purple', '紫色'),
        ('grey', '灰色'),
        ('pink', '粉色'),
        ('orange', '橙色'),
        ('brown', '棕色'),
        ('other', '其他')
    ]
    
    SIZE_CHOICES = [
        ('', '无尺码'),
        ('XS', 'XS'),
        ('S', 'S'),
        ('M', 'M'),
        ('L', 'L'),
        ('XL', 'XL'),
        ('XXL', 'XXL'),
        ('XXXL', 'XXXL'),
        ('35', '35'),
        ('36', '36'),
        ('37', '37'),
        ('38', '38'),
        ('39', '39'),
        ('40', '40'),
        ('41', '41'),
        ('42', '42'),
        ('43', '43'),
        ('44', '44'),
        ('45', '45'),
        ('other', '其他')
    ]

    SEASON_CHOICES = [
        ('', '不限'),
        ('spring', '春季'),
        ('summer', '夏季'),
        ('autumn', '秋季'),
        ('winter', '冬季'),
        ('all', '四季通用'),
    ]

    AUDIENCE_CHOICES = [
        ('', '不限'),
        ('female', '女性'),
        ('male', '男性'),
        ('student', '学生'),
        ('office', '职场通勤'),
        ('mom', '年轻妈妈'),
        ('all', '通用'),
    ]
    
    barcode = models.CharField(max_length=100, unique=True, verbose_name='商品条码')
    scan_code = models.CharField(
        max_length=20, blank=True, default='', db_index=True,
        verbose_name='扫码码(贴纸条码)',
        help_text='供扫码枪扫描的纯数字码(EAN-13),贴纸打印用;与商品条码(可含款号色码)分离')
    model_no = models.CharField(
        max_length=64, blank=True, default='', db_index=True,
        verbose_name='款号',
        help_text='同款不同色码共享款号,用于聚合成鞋款(过渡方案)'
    )
    brand = models.CharField(max_length=64, blank=True, default='', verbose_name='品牌')
    season = models.CharField(max_length=16, choices=SEASON_CHOICES, blank=True, default='', verbose_name='适穿季节')
    audience = models.CharField(max_length=16, choices=AUDIENCE_CHOICES, blank=True, default='', verbose_name='目标人群')
    supplier = models.ForeignKey(
        'Supplier', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='products', verbose_name='主供应商')
    name = models.CharField(max_length=200, verbose_name='商品名称')
    category = models.ForeignKey(Category, on_delete=models.PROTECT, verbose_name='商品分类')
    description = models.TextField(blank=True, verbose_name='商品描述')
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='售价')
    cost = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='成本价')
    image = models.ImageField(upload_to=product_image_path, blank=True, null=True, verbose_name='商品图片')
    # 新增字段
    specification = models.CharField(max_length=200, blank=True, verbose_name='规格')
    manufacturer = models.CharField(max_length=200, blank=True, verbose_name='制造商')
    color = models.CharField(max_length=20, blank=True, default='', verbose_name='颜色', help_text='自由输入,如 黑色/米白/黑白拼色')
    size = models.CharField(max_length=10, blank=True, default='', verbose_name='尺码', help_text='自由输入,如 39/40.5/均码')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    
    def clean(self):
        if self.price < 0:
            raise ValidationError('售价不能为负数')
        if self.cost < 0:
            raise ValidationError('成本价不能为负数')

    def save(self, *args, **kwargs):
        # 自动生成扫码码(scan_code,合法 EAN-13),供扫码枪扫描/贴纸打印;与商品条码(可含款号色码)分离
        if not self.scan_code:
            self.scan_code = _gen_scan_code()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = '商品'
        verbose_name_plural = '商品'

    def __str__(self):
        return self.name


class ProductImage(models.Model):
    """商品图片模型"""
    IMAGE_TYPES = [
        ('main', '白底主图'),
        ('side', '侧面图'),
        ('sole', '鞋底图'),
        ('detail', '细节特写'),
        ('on_foot', '上脚穿搭'),
    ]
    product = models.ForeignKey(Product, related_name='images', on_delete=models.CASCADE, verbose_name='商品')
    image_type = models.CharField(max_length=20, choices=IMAGE_TYPES, default='main', verbose_name='图片类型')
    image = models.ImageField(upload_to=product_image_path, verbose_name='图片')
    thumbnail = models.CharField(max_length=255, blank=True, null=True, verbose_name='缩略图路径')
    alt_text = models.CharField(max_length=255, blank=True, verbose_name='替代文本')
    order = models.IntegerField(default=0, verbose_name='排序')
    is_primary = models.BooleanField(default=False, verbose_name='是否主图')
    
    class Meta:
        verbose_name = '商品图片'
        verbose_name_plural = '商品图片'
        ordering = ['order']
    
    def __str__(self):
        return f"{self.product.name} - 图片 {self.id}"
    
    def save(self, *args, **kwargs):
        # 如果标记为主图，确保其他图片不是主图
        if self.is_primary:
            ProductImage.objects.filter(product=self.product, is_primary=True).update(is_primary=False)
        super(ProductImage, self).save(*args, **kwargs)


class ProductBatch(models.Model):
    """商品批次模型"""
    product = models.ForeignKey(Product, related_name='batches', on_delete=models.CASCADE, verbose_name='商品')
    batch_number = models.CharField(max_length=100, verbose_name='批次号')
    production_date = models.DateField(null=True, blank=True, verbose_name='生产日期')
    expiry_date = models.DateField(null=True, blank=True, verbose_name='过期日期')
    quantity = models.IntegerField(default=0, verbose_name='数量')
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='成本价')
    supplier = models.ForeignKey('Supplier', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='供应商')
    remarks = models.TextField(blank=True, verbose_name='备注')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, related_name='created_batches', verbose_name='创建人')
    
    class Meta:
        verbose_name = '商品批次'
        verbose_name_plural = '商品批次'
        unique_together = ('product', 'batch_number')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.product.name} - {self.batch_number}"


class Supplier(models.Model):
    """供应商模型"""
    name = models.CharField(max_length=100, verbose_name='供应商名称')
    contact_person = models.CharField(max_length=50, blank=True, verbose_name='联系人')
    phone = models.CharField(max_length=20, blank=True, verbose_name='联系电话')
    email = models.EmailField(blank=True, verbose_name='电子邮件')
    address = models.TextField(blank=True, verbose_name='地址')
    remarks = models.TextField(blank=True, verbose_name='备注')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    
    class Meta:
        verbose_name = '供应商'
        verbose_name_plural = '供应商'
    
    def __str__(self):
        return self.name 