from django.core.management.base import BaseCommand
from inventory.models import Supplier

# 常见鞋类供应商(按需增删/改名)。update_or_create 按名称,可重复执行。
SUPPLIERS = [
    {'name': '欧乐琳', 'contact_person': '', 'phone': '',
     'remarks': '商路花小程序供应商', 'is_active': True},
    {'name': '默认供应商', 'contact_person': '', 'phone': '',
     'remarks': '占位,可在供应商管理改名或删除', 'is_active': True},
]


class Command(BaseCommand):
    help = '种子常见供应商(按名称 update_or_create,可重复执行)'

    def handle(self, *args, **options):
        created = 0
        for s in SUPPLIERS:
            obj, was_created = Supplier.objects.update_or_create(
                name=s['name'], defaults=s)
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(
            f'供应商种子完成:共 {len(SUPPLIERS)} 家,新建 {created} 家'))
