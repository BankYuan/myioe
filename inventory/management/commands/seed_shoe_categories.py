"""
初始化鞋类目主数据(对齐内容平台 xhs 的 8 个一级类目)。

运行:
    python manage.py seed_shoe_categories

幂等:重复运行不会重复创建;已存在的类目会被更新。
注:二级类目已废弃(只保留一级),旧版 seed 生成的二级需另行清理。
"""
from django.core.management.base import BaseCommand

from inventory.models import Category

# xhs 标准一级鞋类目 —— code 与内容平台 ShoeProfile.category_l1 完全一致
SHOE_CATEGORIES_L1 = [
    ('pumps_heels', '浅口高跟'),
    ('flats', '平底鞋'),
    ('boots', '靴子'),
    ('sandals_slides', '凉鞋拖鞋'),
    ('sneakers', '运动休闲'),
    ('evening_bridal', '宴会礼服'),
    ('dance_performance', '专业舞鞋'),
    ('functional', '功能鞋'),
]


class Command(BaseCommand):
    help = '初始化鞋类目主数据(8 个一级,对齐内容平台 xhs)'

    def handle(self, *args, **options):
        created = 0
        updated = 0

        # 一级类目:l1_code == code
        for code, name in SHOE_CATEGORIES_L1:
            _, was_created = Category.objects.update_or_create(
                code=code,
                defaults={
                    'name': name,
                    'code': code,
                    'l1_code': code,
                    'description': f'{name}类鞋款',
                    'is_active': True,
                },
            )
            created += int(was_created)
            updated += int(not was_created)

        self.stdout.write(self.style.SUCCESS(
            f'鞋类目初始化完成:新增 {created} 个,更新 {updated} 个(共 {created + updated} 个一级)'
        ))
