# 导入会员相关视图
from .member import (
    member_search_by_phone,
    member_list,
    member_detail,
    member_create,
    member_update,
    member_delete,
    member_edit,  # 别名函数，保持兼容性
    member_details,  # 别名函数，保持兼容性
    member_add_ajax,
    member_level_list,
    member_level_create,
    member_level_update,
    member_level_edit,  # 别名函数，保持兼容性
    member_level_delete,
    member_import,
    member_export,
    member_points_adjust,
    member_recharge,
    member_recharge_records,
    member_balance_adjust
)

# 导入商品相关视图
from .product import (
    product_list,
    product_create,
    product_edit,
    product_update,
    product_detail,
    product_delete,
    product_import,
    product_export
)

# 导入条码相关视图
from .barcode import (
    barcode_lookup,
    barcode_scan,
    product_by_barcode,
    scan_barcode,
    get_product_batches,
)

# 导入核心视图
from .core import (
    index,
    reports_index
)

# 导入库存相关视图
from .inventory import (
    inventory_list,
    inventory_transaction_list,
    inventory_in,
    inventory_out,
    inventory_adjust,
    inventory_transaction_create,
)

# 导入系统相关视图
from .system import (
    system_settings,
    system_info,
    system_maintenance,
)

# 导入销售相关视图
from .sales import (
    sale_list,
    sale_detail,
    sale_create,
    sale_item_create,
    sale_complete,
    sale_cancel,
    sale_delete_item,
    member_purchases,
    birthday_members_report,
)

# 通配符导入已移除以避免循环引用
# from inventory.views.barcode import *
# 其他视图模块导入，根据需要逐步添加
# from inventory.views.product import *
# from inventory.views.inventory import *
# from inventory.views.inventory_check import *
# from inventory.views.member import *
# from inventory.views.report import *
# from inventory.views.system import * 