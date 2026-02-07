# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

_logger = logging.getLogger(__name__)


class StockLotReplacementWizard(models.TransientModel):
    _name = 'stock.lot.replacement.wizard'
    _description = 'Wizard de Reemplazo de Lotes'

    picking_id = fields.Many2one(
        'stock.picking',
        string='Devolución',
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='picking_id.partner_id',
        string='Cliente',
        readonly=True,
    )
    picking_type_id = fields.Many2one(
        'stock.picking.type',
        string='Tipo de Operación (Entrega)',
        readonly=True,
    )
    line_ids = fields.One2many(
        'stock.lot.replacement.line',
        'wizard_id',
        string='Líneas de Reemplazo',
    )
    has_lines = fields.Boolean(
        compute='_compute_has_lines',
    )

    @api.depends('line_ids')
    def _compute_has_lines(self):
        for wizard in self:
            wizard.has_lines = bool(wizard.line_ids)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        active_id = self.env.context.get('active_id')
        if not active_id:
            return res

        picking = self.env['stock.picking'].browse(active_id)
        if not picking.exists():
            raise UserError(_('No se encontró la orden de devolución.'))

        if picking.state != 'done':
            raise UserError(_('La devolución debe estar validada para crear un reemplazo.'))

        # Buscar el tipo de operación de entrega (salida) del mismo almacén
        warehouse = picking.picking_type_id.warehouse_id
        delivery_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'outgoing'),
        ], limit=1)

        if not delivery_type:
            raise UserError(_('No se encontró un tipo de operación de entrega para el almacén %s.') % warehouse.name)

        res['picking_id'] = picking.id
        res['picking_type_id'] = delivery_type.id

        # Generar líneas a partir de los move_lines de la devolución
        lines = []
        for move in picking.move_ids:
            if move.state != 'done':
                continue
            if move.product_id.tracking not in ('lot', 'serial'):
                continue

            # Obtener lotes devueltos
            done_lines = move.move_line_ids.filtered(
                lambda ml: ml.state == 'done' and ml.lot_id
            )
            lot_qty_map = {}
            for ml in done_lines:
                lot_qty_map[ml.lot_id.id] = lot_qty_map.get(ml.lot_id.id, 0.0) + ml.quantity

            for lot_id, qty in lot_qty_map.items():
                lot = self.env['stock.lot'].browse(lot_id)
                lines.append((0, 0, {
                    'product_id': move.product_id.id,
                    'returned_lot_id': lot_id,
                    'returned_qty': qty,
                    'product_uom_id': move.product_uom.id,
                    'original_move_id': move.id,
                    'to_replace': True,
                }))

        if not lines:
            raise UserError(_('No se encontraron productos con lotes en esta devolución.'))

        res['line_ids'] = lines
        return res

    def action_create_replacement(self):
        """Crea la orden de entrega de reemplazo con los lotes seleccionados."""
        self.ensure_one()

        active_lines = self.line_ids.filtered('to_replace')
        if not active_lines:
            raise UserError(_('Seleccione al menos una línea para reemplazar.'))

        # Validar que todas las líneas activas tengan lotes seleccionados
        lines_without_lots = active_lines.filtered(lambda l: not l.replacement_lot_ids)
        if lines_without_lots:
            products = ', '.join(lines_without_lots.mapped('product_id.name'))
            raise UserError(_(
                'Seleccione lotes de reemplazo para: %s'
            ) % products)

        # Validar disponibilidad de stock
        for line in active_lines:
            for lot in line.replacement_lot_ids:
                quant = self.env['stock.quant'].search([
                    ('lot_id', '=', lot.id),
                    ('product_id', '=', line.product_id.id),
                    ('location_id.usage', '=', 'internal'),
                    ('quantity', '>', 0),
                ], limit=1)
                if not quant:
                    raise UserError(_(
                        'El lote "%s" del producto "%s" no tiene stock disponible.'
                    ) % (lot.name, line.product_id.name))

        # Crear el picking de reemplazo
        picking_vals = self._prepare_replacement_picking()
        new_picking = self.env['stock.picking'].create(picking_vals)

        # Crear moves y move_lines
        for line in active_lines:
            move_vals = line._prepare_replacement_move(new_picking)
            new_move = self.env['stock.move'].create(move_vals)

            for lot in line.replacement_lot_ids:
                qty = line._get_lot_available_qty(lot)
                if float_compare(qty, 0.0, precision_digits=4) <= 0:
                    continue
                self.env['stock.move.line'].create({
                    'move_id': new_move.id,
                    'picking_id': new_picking.id,
                    'product_id': line.product_id.id,
                    'product_uom_id': line.product_uom_id.id,
                    'lot_id': lot.id,
                    'quantity': qty,
                    'location_id': new_move.location_id.id,
                    'location_dest_id': new_move.location_dest_id.id,
                    'company_id': new_picking.company_id.id,
                })

        # Confirmar el picking
        new_picking.action_confirm()

        _logger.info(
            '[LOT_REPLACEMENT] Created replacement picking %s from return %s',
            new_picking.name, self.picking_id.name,
        )

        return {
            'name': _('Entrega de Reemplazo'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': new_picking.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _prepare_replacement_picking(self):
        """Prepara los valores para crear el picking de reemplazo."""
        return {
            'picking_type_id': self.picking_type_id.id,
            'partner_id': self.partner_id.id,
            'origin': _('Reemplazo: %s') % self.picking_id.name,
            'location_id': self.picking_type_id.default_location_src_id.id,
            'location_dest_id': self.picking_type_id.default_location_dest_id.id or self.partner_id.property_stock_customer.id,
            'replacement_origin_picking_id': self.picking_id.id,
            'company_id': self.picking_id.company_id.id,
        }


class StockLotReplacementLine(models.TransientModel):
    _name = 'stock.lot.replacement.line'
    _description = 'Línea de Reemplazo de Lote'

    wizard_id = fields.Many2one(
        'stock.lot.replacement.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Producto',
        required=True,
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='UdM',
        readonly=True,
    )
    returned_lot_id = fields.Many2one(
        'stock.lot',
        string='Lote Devuelto',
        readonly=True,
    )
    returned_qty = fields.Float(
        string='Cant. Devuelta',
        readonly=True,
    )
    original_move_id = fields.Many2one(
        'stock.move',
        string='Movimiento Original',
        readonly=True,
    )
    to_replace = fields.Boolean(
        string='Reemplazar',
        default=True,
    )
    replacement_lot_ids = fields.Many2many(
        'stock.lot',
        'stock_lot_replacement_line_lot_rel',
        'line_id', 'lot_id',
        string='Lotes de Reemplazo',
    )
    available_lot_ids = fields.Many2many(
        'stock.lot',
        'stock_lot_replacement_line_avail_lot_rel',
        'line_id', 'lot_id',
        string='Lotes Disponibles',
        compute='_compute_available_lot_ids',
    )
    replacement_qty = fields.Float(
        string='Cant. a Entregar',
        compute='_compute_replacement_qty',
        store=True,
    )

    @api.depends('product_id')
    def _compute_available_lot_ids(self):
        """Calcula lotes disponibles en inventario para el producto."""
        for line in self:
            if not line.product_id or line.product_id.tracking not in ('lot', 'serial'):
                line.available_lot_ids = False
                continue

            # Buscar lotes con stock disponible en ubicaciones internas
            quants = self.env['stock.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('location_id.usage', '=', 'internal'),
                ('quantity', '>', 0),
                ('lot_id', '!=', False),
            ])
            line.available_lot_ids = quants.mapped('lot_id')

    @api.depends('replacement_lot_ids', 'to_replace')
    def _compute_replacement_qty(self):
        for line in self:
            if not line.to_replace or not line.replacement_lot_ids:
                line.replacement_qty = 0.0
                continue

            total = 0.0
            for lot in line.replacement_lot_ids:
                total += line._get_lot_available_qty(lot)
            line.replacement_qty = total

    @api.onchange('replacement_lot_ids')
    def _onchange_replacement_lot_ids(self):
        for line in self:
            if line.replacement_lot_ids:
                line.to_replace = True
            else:
                line.replacement_qty = 0.0

    @api.onchange('to_replace')
    def _onchange_to_replace(self):
        for line in self:
            if not line.to_replace:
                line.replacement_lot_ids = [(5, 0, 0)]
                line.replacement_qty = 0.0

    def _get_lot_available_qty(self, lot):
        """Obtiene la cantidad disponible de un lote en ubicaciones internas."""
        quants = self.env['stock.quant'].search([
            ('lot_id', '=', lot.id),
            ('product_id', '=', self.product_id.id),
            ('location_id.usage', '=', 'internal'),
        ])
        return sum(quants.mapped('quantity'))

    def _prepare_replacement_move(self, picking):
        """Prepara los valores del stock.move de reemplazo."""
        return {
            'name': _('Reemplazo: %s') % self.product_id.display_name,
            'product_id': self.product_id.id,
            'product_uom_qty': self.replacement_qty,
            'product_uom': self.product_uom_id.id,
            'picking_id': picking.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': picking.company_id.id,
        }
