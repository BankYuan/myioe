# 从各表单模块导入
from .product_forms import (
    ProductForm, CategoryForm, ProductBatchForm,
    ProductImageFormSet, ProductImportForm
)
from .inventory_check_forms import InventoryCheckForm, InventoryCheckItemForm, InventoryCheckApproveForm
from .member_forms import MemberForm, MemberLevelForm, RechargeForm, MemberImportForm
from .inventory_forms import InventoryTransactionForm
from .sales_forms import SaleForm, SaleItemForm
from .report_forms import (
    DateRangeForm, TopProductsForm, InventoryTurnoverForm,
    ReportFilterForm, SalesReportForm
)
from .system_forms import SystemConfigForm

# 在完全重构完成之前，继续从原始表单文件导入
from inventory.forms_batch import (
    BatchProductImportForm, BatchInventoryUpdateForm, ProductBatchDeleteForm
)

# 导出所有表单，使其可以从inventory.forms访问
__all__ = [
    # 产品表单
    'ProductForm', 'CategoryForm', 'ProductBatchForm',
    'ProductImageFormSet', 'ProductImportForm',
    
    # 库存盘点表单
    'InventoryCheckForm', 'InventoryCheckItemForm', 'InventoryCheckApproveForm',
    
    # 会员表单
    'MemberForm', 'MemberLevelForm', 'RechargeForm', 'MemberImportForm',
    
    # 库存管理表单
    'InventoryTransactionForm',
    
    # 销售表单
    'SaleForm', 'SaleItemForm',
    
    # 报表表单
    'DateRangeForm', 'TopProductsForm', 'InventoryTurnoverForm',
    'ReportFilterForm', 'SalesReportForm',
    
    # 系统配置表单
    'SystemConfigForm',
    
    # 批量操作表单
    'BatchProductImportForm', 'BatchInventoryUpdateForm', 'ProductBatchDeleteForm',
]

# 后续会逐步导入其他表单，如：
# from .inventory_forms import InventoryTransactionForm
# from .sales_forms import SaleForm, SaleItemForm 