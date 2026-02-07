# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    is_return_picking = fields.Boolean(
        string='Es Devolución',
        compute='_compute_is_return_picking',
        store=True,
    )
    replacement_picking_ids = fields.One2many(
        'stock.picking',
        'replacement_origin_picking_id',
        string='Entregas de Reemplazo',
    )
    replacement_origin_picking_id = fields.Many2one(
        'stock.picking',
        string='Devolución de Origen',
        readonly=True,
        copy=False,
    )
    replacement_count = fields.Integer(
        string='Reemplazos',
        compute='_compute_replacement_count',
    )

    def _auto_init(self):
        res = super()._auto_init()
        self.env.cr.execute("""
            UPDATE stock_picking sp
            SET is_return_picking = TRUE
            WHERE EXISTS (
                SELECT 1 FROM stock_move sm
                WHERE sm.picking_id = sp.id
                AND sm.origin_returned_move_id IS NOT NULL
            )
            AND (sp.is_return_picking IS NULL OR sp.is_return_picking = FALSE)
        """)
        return res

    @api.depends('move_ids.origin_returned_move_id')
    def _compute_is_return_picking(self):
        for picking in self:
            picking.is_return_picking = bool(
                picking.move_ids.filtered('origin_returned_move_id')
            )

    @api.depends('replacement_picking_ids')
    def _compute_replacement_count(self):
        for picking in self:
            picking.replacement_count = len(picking.replacement_picking_ids)

    def action_open_lot_replacement_wizard(self):
        """Abre el wizard de reemplazo de lotes."""
        self.ensure_one()
        return {
            'name': _('Reemplazo de Lotes'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.lot.replacement.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
                'active_model': 'stock.picking',
            },
        }

    def action_view_replacement_pickings(self):
        """Abre la vista de entregas de reemplazo."""
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('stock.action_picking_tree_all')
        if self.replacement_count == 1:
            action['views'] = [(False, 'form')]
            action['res_id'] = self.replacement_picking_ids[0].id
        else:
            action['domain'] = [('id', 'in', self.replacement_picking_ids.ids)]
        return action