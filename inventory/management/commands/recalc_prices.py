"""按定价规则批量重算商品售价与折扣价。
公式(与收银台 JS 逻辑一致):
  定价   = 成本 * 2.3
  折扣后 = 定价   * 0.75

执行:
    python manage.py recalc_prices            # 实际改写
    python manage.py recalc_prices --dry-run  # 只预览不改库

说明:
- 只处理有成本价(cost>0)的商品；无成本价/0 的跳过。
- update_fields 只写 price/discount_price，不会影响其他字段。
- 重复执行结果一致，幂等。
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from inventory.models import Product

PRICE_MULTIPLIER = Decimal('2.3')      # 定价 = 成本 * 2.3
DISCOUNT_MULTIPLIER = Decimal('0.75')  # 折扣后 = 定价 * 0.75


class Command(BaseCommand):
    help = '按定价规则批量重算商品售价与折扣价'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='只打印将要修改的商品，不写数据库')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        prefix = '[DRY] ' if dry else ''

        qs = Product.objects.exclude(cost__isnull=True).exclude(cost=0).order_by('id')
        total = qs.count()
        self.stdout.write(f'{prefix}待重算商品(有成本价): {total} 个')

        changed = 0
        samples = []
        for p in qs:
            new_price = (p.cost * PRICE_MULTIPLIER).quantize(Decimal('1'))
            new_discount = (new_price * DISCOUNT_MULTIPLIER).quantize(Decimal('1'))
            if not dry:
                p.price = new_price
                p.discount_price = new_discount
                p.save(update_fields=['price', 'discount_price'])
            changed += 1
            if len(samples) < 5:
                samples.append((p.id, p.name[:14], p.cost, new_price, new_discount))

        self.stdout.write('')
        self.stdout.write(f'{prefix}示例(前5个)(成本->定价->折扣后):')
        for sid, name, cost, pr, dp in samples:
            self.stdout.write(
                f'  #{sid} {name:<16} {cost} -> {pr} -> {dp}')

        no_cost = Product.objects.filter(cost__isnull=True).count() + \
            Product.objects.filter(cost=0).count()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}完成:重算 {changed} 个,跳过(无成本价){no_cost} 个'))