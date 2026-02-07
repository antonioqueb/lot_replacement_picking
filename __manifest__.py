# -*- coding: utf-8 -*-
{
    'name': 'Reemplazo de Lotes en Devoluciones',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Crear órdenes de entrega de reemplazo desde devoluciones con selección de lotes',
    'description': """
Reemplazo de Lotes en Devoluciones
===================================
Agrega un botón "Reemplazo" en las órdenes de devolución (recepciones que nacen
de una devolución) que permite:

- Seleccionar uno o múltiples lotes del mismo producto como reemplazo
- Ver la cantidad total que se va a entregar
- Crear automáticamente una nueva orden de entrega con los lotes seleccionados
- Relacionar la entrega de reemplazo con la devolución original

Flujo:
1. Se realiza una devolución (usando el módulo de devolución por lotes)
2. En la orden de devolución validada, se presiona "Reemplazo"
3. Se seleccionan los lotes de reemplazo disponibles en inventario
4. Se confirma y se genera la orden de entrega de reemplazo
    """,
    'author': 'Alphaqueb Consulting',
    'website': 'https://www.alphaqueb.com',
    'license': 'LGPL-3',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_picking_views.xml',
        'wizard/stock_lot_replacement_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
