"""
按定价规则批量重算商品售价与折后价。

规则(与录入页 JS 联动一致):
    售价   = 成本价 × 2.3
    折后价 = 售价   × 0.75

运行:
    python manage.py recalc_prices            # 真改
    python manage.py recalc_prices --dry-run  # 只预览,不改库

说明:
- 只处理有成本价(cost>0)的商品;成本为空/0 的跳过(无法算)。
- update_fields 仅写 price/discount_price,不触发其他字段副作用。
- 重复运行幂等,结果一致。
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from inventory.models import Product

PRICE_MULTIPLIER = Decimal('2.3')      # 售价 = 成本 × 2.3
DISCOUNT_MULTIPLIER = Decimal('0.75')  # 折后 = 售价 × 0.75


class Command(BaseCommand):
    help = '按定价规则批量重算售价(成本×2.3)与折后价(售价×0.75)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='只打印将变更的商品,不写库')

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
        self.stdout.write(f'{prefix}示例(前5个,成本→售价→折后):')
        for sid, name, cost, pr, dp in samples:
            self.stdout.write(
                f'  #{sid} {name:<16} {cost} → {pr} → {dp}')

        skipped = Product.objects.exclude(cost__isnull=True).exclude(cost=0).count()
        no_cost = Product.objects.filter(cost__isnull=True).count() + \
            Product.objects.filter(cost=0).count()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}完成:重算 {changed} 个,跳过(无成本价){no_cost} 个'))
