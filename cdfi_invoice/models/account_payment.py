# -*- coding: utf-8 -*-

import base64
import json
import logging
import ast
import math
from datetime import datetime

import pytz
import requests
from lxml import etree
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.units import mm
import re
from odoo import api, fields, models, _
from . import amount_to_text_es_MX

_logger = logging.getLogger(__name__)


class AccountRegisterPayment(models.TransientModel):
    _inherit = 'account.payment.register'

    def validate_complete_payment(self):
        for rec in self:
            payments = rec._create_payments()
            if len(payments) > 1:
                return
            else:
                return {
                    'name': _('Payments'),
                    'view_type': 'form',
                    'view_mode': 'form',
                    'res_model': 'account.payment',
                    'view_id': False,
                    'type': 'ir.actions.act_window',
                    'res_id': payments.id,
                }

    def _create_payment_vals_from_wizard(self, batch_result):
        res = super(AccountRegisterPayment, self)._create_payment_vals_from_wizard(batch_result)

        timezone = self._context.get('tz')
        if not timezone:
            timezone = self.env.user.partner_id.tz or 'America/Mexico_City'
        local = pytz.timezone(timezone)
        naive_from = self.payment_date
        res.update({'fecha_pago': datetime(self.payment_date.year, self.payment_date.month, self.payment_date.day, 16,
                                           0, tzinfo=local).strftime("%Y-%m-%d %H:%M:%S")})
        return res

    company_cfdi = fields.Boolean(related="company_id.company_cfdi", store=True)


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    forma_pago_id = fields.Many2one('catalogo.forma.pago', string='Forma de pago')
    forma_de_pago = fields.Char(related="forma_pago_id.code", string="Forma pago")

    methodo_pago = fields.Selection(
        selection=[('PUE', 'Pago en una sola exhibición'),
                   ('PPD', 'Pago en parcialidades o diferido'), ],
        string='Método de pago',
    )
    # no_de_pago = fields.Integer("No. de pago", readonly=True)
    # saldo_pendiente = fields.Float("Saldo pendiente", readonly=True)
    # monto_pagar = fields.Float("Monto a pagar", compute='_compute_monto_pagar')
    # saldo_restante = fields.Float("Saldo restante", readonly=True)
    fecha_pago = fields.Datetime("Fecha de pago")
    date_payment = fields.Datetime("Fecha de CFDI", copy=False)
    cuenta_emisor = fields.Many2one('res.partner.bank', string='Cuenta del emisor')
    banco_emisor = fields.Char("Banco del emisor", related='cuenta_emisor.bank_name', readonly=True)
    rfc_banco_emisor = fields.Char("RFC banco emisor", related='cuenta_emisor.bank_bic', readonly=True)
    numero_operacion = fields.Char("Número de operación")
    banco_receptor = fields.Char("Banco receptor", compute='_compute_banco_receptor')
    cuenta_beneficiario = fields.Char("Cuenta beneficiario", compute='_compute_banco_receptor')
    rfc_banco_receptor = fields.Char("RFC banco receptor", compute='_compute_banco_receptor')
    estado_pago = fields.Selection(
        selection=[('pago_no_enviado', 'REP no generado'), ('pago_correcto', 'REP correcto'),
                   ('problemas_factura', 'Problemas con el pago'), ('solicitud_cancelar', 'Cancelación en proceso'),
                   ('cancelar_rechazo', 'Cancelación rechazada'), ('factura_cancelada', 'REP cancelado'), ],
        string='Estado CFDI',
        default='pago_no_enviado',
        readonly=True, copy=False
    )
    tipo_relacion = fields.Selection(
        selection=[('04', 'Sustitución de los CFDI previos'), ],
        string='Tipo relación',
    )
    uuid_relacionado = fields.Char(string='CFDI Relacionado')
    confirmacion = fields.Char(string='Confirmación')
    folio_fiscal = fields.Char(string='Folio Fiscal', readonly=True, copy=False)
    numero_cetificado = fields.Char(string='Numero de certificado')
    cetificaso_sat = fields.Char(string='Cetificado SAT')
    fecha_certificacion = fields.Char(string='Fecha y Hora Certificación')
    cadena_origenal = fields.Char(string='Cadena Original del Complemento digital de SAT')
    selo_digital_cdfi = fields.Char(string='Sello Digital del CDFI')
    selo_sat = fields.Char(string='Sello del SAT')
    #   moneda = fields.Char(string='Moneda')
    monedap = fields.Char(string='Moneda')
    #    tipocambio = fields.Char(string='TipoCambio')
    tipocambiop = fields.Char(string='TipoCambio')
    #folio = fields.Char(string='Folio')
    #  version = fields.Char(string='Version')
    number_folio = fields.Char(string='Folio', compute='_get_number_folio')
    amount_to_text = fields.Char('Amount to Text', compute='_get_amount_to_text',
                                 size=256,
                                 help='Amount of the invoice in letter')
    qr_value = fields.Char(string='QR Code Value')
    qrcode_image = fields.Binary("QRCode")
    #    rfc_emisor = fields.Char(string='RFC')
    #    name_emisor = fields.Char(string='Name')
    xml_payment_link = fields.Char(string='XML link', readonly=True)
    payment_mail_ids = fields.One2many('account.payment.mail', 'payment_id', string='Payment Mails')
    iddocumento = fields.Char(string='iddocumento')
    fecha_emision = fields.Char(string='Fecha y Hora Certificación')
    docto_relacionados = fields.Text("Docto relacionados", default='[]')
    docto_relacionados_data = fields.Text("Docto relacionados procesados", help="Almacena los datos procesados de add_resitual_amounts")
    cep_sello = fields.Char(string='cep_sello')
    cep_numeroCertificado = fields.Char(string='cep_numeroCertificado')
    cep_cadenaCDA = fields.Char(string='cep_cadenaCDA')
    cep_claveSPEI = fields.Char(string='cep_claveSPEI')
    retencionesp = fields.Text("traslados P", default='[]')
    trasladosp = fields.Text("retenciones P", default='[]')
    total_pago = fields.Float("Total pagado")
    partials_payment_ids = fields.One2many('facturas.pago', 'doc_id', 'Montos')
    manual_partials = fields.Boolean("Montos manuales")
    different_currency = fields.Boolean("Diferente moneda", compute='_compute_different_currency')
    company_cfdi = fields.Boolean(related="company_id.company_cfdi", store=True)
    redondeo_t_base = fields.Selection(
        selection=[('01', 'Tradicional'),
                   ('02', 'Decimal'),
                   ('03', 'Techo'),
                   ('04', 'Truncar'),],
        default='01',
        string='Redondeo base',
    )
    redondeo_t_impuesto = fields.Selection(
        selection=[('01', 'Tradicional'),
                   ('02', 'Decimal'),
                   ('03', 'Techo'),
                   ('04', 'Truncar'),],
        default='01',
        string='Redondeo impuesto',
    )
    redondeo_t_total = fields.Selection(
        selection=[('01', 'Tradicional'),
                   ('02', 'Decimal'),
                   ('03', 'Techo'),
                   ('04', 'Truncar'),],
        default='01',
        string='Redondeo total', 
    )

    @api.depends('name')
    def _get_number_folio(self):
        for record in self:
            if record.name:
                record.number_folio = record.name.replace('CUST.IN', '').replace('/', '')

    @api.model
    def get_docto_relacionados(self, payment):
        try:
            data = json.loads(payment.docto_relacionados)
        except Exception:
            data = []
        return data

    def _compute_different_currency(self):
        for payment in self:
            if payment.reconciled_invoice_ids:
                for invoice in payment.reconciled_invoice_ids:
                    if invoice.currency_id != payment.currency_id:
                        payment.different_currency = True
                        break
                    else:
                        payment.different_currency = False
            else:
                payment.different_currency = False

    def importar_incluir_cep(self):
        ctx = {'default_payment_id': self.id}
        return {
            'name': _('Importar factura de compra'),
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': self.env.ref('cdfi_invoice.view_import_xml_payment_in_payment_form_view').id,
            'res_model': 'import.account.payment.from.xml',
            'context': ctx,
            'type': 'ir.actions.act_window',
            'target': 'new',
        }

    @api.onchange('journal_id')
    def _onchange_journal(self):
        if self.journal_id:
            self.currency_id = self.journal_id.currency_id or self.company_id.currency_id
            # Set default payment method (we consider the first to be the default one)
            payment_methods = self.payment_type == 'inbound' and self.journal_id.inbound_payment_method_line_ids or self.journal_id.outbound_payment_method_line_ids
            self.payment_method_line_id = payment_methods and payment_methods[0] or False
            # Set payment method domain (restrict to methods enabled for the journal and to selected payment type)
            payment_type = self.payment_type in ('outbound', 'transfer') and 'outbound' or 'inbound'
            self.forma_pago_id = self.journal_id.forma_pago_id.id
            return {'domain': {
                'payment_method_line_id': [('payment_type', '=', payment_type), ('id', 'in', payment_methods.ids)]}}
        return {}

    # @api.onchange('date')
    # def _onchange_payment_date(self):
    #     if self.date:
    #         self.fecha_pago = datetime.combine((self.date), datetime.max.time())

    def add_resitual_amounts(self):
        for payment in self:
            _logger.info(f"=== EJECUTANDO add_resitual_amounts para pago {payment.name} ===")
            #no_decimales = payment.currency_id.no_decimales
            no_decimales_tc = payment.currency_id.no_decimales_tc
            docto_relacionados = []
            tax_grouped_tras = {}
            tax_grouped_ret = {}
            mxn_currency = self.env["res.currency"].search([('name', '=', 'MXN')], limit=1)

            _logger.info(f"reconciled_invoice_ids: {payment.reconciled_invoice_ids}")
            _logger.info(f"manual_partials: {payment.manual_partials}")
            if payment.reconciled_invoice_ids:
                if payment.manual_partials:
                    for partial in payment.partials_payment_ids:
                        _logger.info(f"Procesando parcial - Factura: {partial.facturas_id.name}")
                        _logger.info(f"  - folio_fiscal: {partial.facturas_id.folio_fiscal}")
                        _logger.info(f"  - total_factura: {partial.facturas_id.total_factura}")
                        _logger.info(f"  - tax_payment: {partial.facturas_id.tax_payment}")
                        
                        equivalenciadr = partial.equivalenciadr
                        if equivalenciadr == 0:
                            raise UserError("La equivalencia debe ser diferente de cero.")

                        if partial.facturas_id.total_factura <= 0:
                            raise UserError(
                                "No hay monto total de la factura. Carga el XML en la factura para agregar el monto total.")

                        paid_pct = float_round(partial.imp_pagado, precision_digits=6,
                                               rounding_method='UP') / partial.facturas_id.total_factura

                        if not partial.facturas_id.tax_payment:
                            raise UserError(
                                "No hay información de impuestos en el documento. Carga el XML en la factura para agregar los impuestos.")

                        taxes = json.loads(partial.facturas_id.tax_payment)
                        objetoimpdr = '01'
                        trasladodr = []
                        retenciondr = []
                        if "translados" in taxes:
                            objetoimpdr = '02'
                            traslados = taxes['translados']
                            for traslado in traslados:
                                basedr = float_round(float(traslado['base']) * paid_pct, precision_digits=2,
                                                     rounding_method='UP')
                                importedr = traslado['importe'] and float_round(float(traslado['tasa']) * basedr,
                                                                                precision_digits=2,
                                                                                rounding_method='UP') or 0
                                trasladodr.append({
                                    'BaseDR': payment.set_decimals(basedr, 2),
                                    'ImpuestoDR': traslado['impuesto'],
                                    'TipoFactorDR': traslado['TipoFactor'],
                                    'TasaOcuotaDR': traslado['tasa'],
                                    'ImporteDR': payment.set_decimals(importedr, 2) if traslado[
                                                                                           'TipoFactor'] != 'Exento' else '',
                                })
                                key = traslado['tax_id']

                                if equivalenciadr == 1:
                                    basep = basedr
                                    importep = importedr
                                else:
                                    basep = basedr / equivalenciadr
                                    importep = importedr / equivalenciadr

                                val = {'BaseP': basep,
                                       'ImpuestoP': traslado['impuesto'],
                                       'TipoFactorP': traslado['TipoFactor'],
                                       'TasaOCuotaP': traslado['tasa'],
                                       'ImporteP': importep, }
                                if key not in tax_grouped_tras:
                                    tax_grouped_tras[key] = val
                                else:
                                    tax_grouped_tras[key]['BaseP'] += basep
                                    tax_grouped_tras[key]['ImporteP'] += importep
                        if "retenciones" in taxes:
                            objetoimpdr = '02'
                            retenciones = taxes['retenciones']
                            for retencion in retenciones:
                                basedr = float_round(float(retencion['base']) * paid_pct, precision_digits=2,
                                                     rounding_method='UP')
                                importedr = retencion['importe'] and float_round(float(retencion['tasa']) * basedr,
                                                                                 precision_digits=2,
                                                                                 rounding_method='UP') or 0
                                retenciondr.append({
                                    'BaseDR': payment.set_decimals(basedr, 2),
                                    'ImpuestoDR': retencion['impuesto'],
                                    'TipoFactorDR': retencion['TipoFactor'],
                                    'TasaOcuotaDR': retencion['tasa'],
                                    'ImporteDR': payment.set_decimals(importedr, 2),
                                })
                                key = retencion['tax_id']

                                if equivalenciadr == 1:
                                    importep = importedr
                                else:
                                    importep = importedr / equivalenciadr

                                val = {'ImpuestoP': retencion['impuesto'],
                                       'ImporteP': importep, }
                                if key not in tax_grouped_ret:
                                    tax_grouped_ret[key] = val
                                else:
                                    tax_grouped_ret[key]['ImporteP'] += importep

                        #if len(payment.partials_payment_ids) > 1 and payment.different_currency:
                        #    if equivalenciadr == 1:
                        #        equivalenciadr = payment.set_decimals(equivalenciadr, 10)
                        docto_relacionados.append({
                            'MonedaDR': partial.facturas_id.moneda,
                            'EquivalenciaDR': equivalenciadr,
                            'IdDocumento': partial.facturas_id.folio_fiscal,
                            'folio_facura': partial.facturas_id.number_folio,
                            'NumParcialidad': partial.parcialidad,
                            'ImpSaldoAnt': partial.imp_saldo_ant,
                            'ImpPagado': partial.imp_pagado,
                            'ImpSaldoInsoluto': partial.imp_saldo_insoluto,
                            'ObjetoImpDR': objetoimpdr,
                            'ImpuestosDR': {'TrasladosDR': trasladodr, 'RetencionesDR': retenciondr, },
                        })

                    payment.write({'docto_relacionados': json.dumps(docto_relacionados),
                                   'docto_relacionados_data': json.dumps(docto_relacionados),
                                   'retencionesp': json.dumps(tax_grouped_ret),
                                   'trasladosp': json.dumps(tax_grouped_tras), })
                else:
                    _logger.info("=== FLUJO AUTOMÁTICO (manual_partials=False) ===")
                    pay_rec_lines = payment.move_id.line_ids.filtered(
                        lambda line: line.account_type in ('asset_receivable', 'liability_payable'))
                    _logger.info(f"pay_rec_lines: {pay_rec_lines}")
                    if payment.currency_id == mxn_currency:
                        rate_payment_curr_mxn = None
                        paid_amount_comp_curr = payment.amount
                    else:
                        rate_payment_curr_mxn = payment.currency_id._convert(1.0, mxn_currency, payment.company_id, payment.date, round=False)
                        paid_amount_comp_curr = payment.currency_id.round(payment.amount * rate_payment_curr_mxn)

                    # Verificar si hay matched_ids
                    has_matched_ids = any(pay_rec_lines.mapped('matched_credit_ids')) or any(pay_rec_lines.mapped('matched_debit_ids'))
                    _logger.info(f"has_matched_ids: {has_matched_ids}")
                    
                    if not has_matched_ids:
                        # FLUJO ALTERNATIVO: Usar directamente reconciled_invoice_ids
                        _logger.info("=== FLUJO ALTERNATIVO: Usando reconciled_invoice_ids directamente ===")
                        for invoice in payment.reconciled_invoice_ids:
                            if not invoice.factura_cfdi:
                                _logger.info(f"Factura {invoice.name} no es CFDI, omitiendo")
                                continue
                            
                            _logger.info(f"Procesando factura: {invoice.name}")
                            decimal_p = 2
                            
                            # Calcular el monto pagado de esta factura
                            # Usar el amount_total si es pago completo o amount_residual si es parcial
                            amount_paid_invoice_curr = payment.amount
                            equivalenciadr = 1
                            
                            if invoice.currency_id != payment.currency_id:
                                # Calcular tipo de cambio
                                if invoice.currency_id == mxn_currency:
                                    equivalenciadr = 1
                                else:
                                    rate_invoice = invoice.currency_id.with_context(date=invoice.date).rate
                                    rate_payment = payment.currency_id.with_context(date=payment.date).rate
                                    if rate_payment > 0:
                                        equivalenciadr = payment.roundTraditional(rate_invoice / rate_payment, 6)
                            
                            # Número de parcialidad
                            payment_content = 1
                            if hasattr(invoice, 'invoice_payments_widget') and invoice.invoice_payments_widget:
                                payment_content = len([w for w in invoice.invoice_payments_widget.get('content', []) if not w.get('is_exchange', False)])
                            
                            paid_pct = amount_paid_invoice_curr / invoice.total_factura if invoice.total_factura > 0 else 1
                            
                            # Procesar impuestos
                            objetoimpdr = '01'
                            trasladodr = []
                            retenciondr = []
                            
                            if invoice.tax_payment:
                                taxes = json.loads(invoice.tax_payment)
                                
                                if "translados" in taxes:
                                    objetoimpdr = '02'
                                    for traslado in taxes['translados']:
                                        basedr = float_round(float(traslado['base']) * paid_pct, precision_digits=decimal_p, rounding_method='UP')
                                        importedr = traslado.get('importe') and float_round(float(traslado['tasa']) * basedr, precision_digits=decimal_p, rounding_method='UP') or 0
                                        trasladodr.append({
                                            'BaseDR': payment.set_decimals(basedr, decimal_p),
                                            'ImpuestoDR': traslado['impuesto'],
                                            'TipoFactorDR': traslado['TipoFactor'],
                                            'TasaOcuotaDR': traslado['tasa'],
                                            'ImporteDR': payment.set_decimals(importedr, decimal_p) if traslado['TipoFactor'] != 'Exento' else '',
                                        })
                                        
                                        key = traslado['tax_id']
                                        basep = basedr / equivalenciadr if equivalenciadr != 1 else basedr
                                        importep = importedr / equivalenciadr if equivalenciadr != 1 else importedr
                                        val = {'BaseP': basep, 'ImpuestoP': traslado['impuesto'], 'TipoFactorP': traslado['TipoFactor'], 'TasaOCuotaP': traslado['tasa'], 'ImporteP': importep}
                                        if key not in tax_grouped_tras:
                                            tax_grouped_tras[key] = val
                                        else:
                                            tax_grouped_tras[key]['BaseP'] += basep
                                            tax_grouped_tras[key]['ImporteP'] += importep
                                
                                if "retenciones" in taxes:
                                    objetoimpdr = '02'
                                    for retencion in taxes['retenciones']:
                                        basedr = float_round(float(retencion['base']) * paid_pct, precision_digits=decimal_p, rounding_method='UP')
                                        importedr = retencion.get('importe') and float_round(float(retencion['tasa']) * basedr, precision_digits=decimal_p, rounding_method='UP') or 0
                                        retenciondr.append({
                                            'BaseDR': payment.set_decimals(basedr, decimal_p),
                                            'ImpuestoDR': retencion['impuesto'],
                                            'TipoFactorDR': retencion['TipoFactor'],
                                            'TasaOcuotaDR': retencion['tasa'],
                                            'ImporteDR': payment.set_decimals(importedr, decimal_p),
                                        })
                                        
                                        key = retencion['tax_id']
                                        importep = importedr / equivalenciadr if equivalenciadr != 1 else importedr
                                        val = {'ImpuestoP': retencion['impuesto'], 'ImporteP': importep}
                                        if key not in tax_grouped_ret:
                                            tax_grouped_ret[key] = val
                                        else:
                                            tax_grouped_ret[key]['ImporteP'] += importep
                            
                            # Calcular saldos
                            imp_saldo_ant = invoice.amount_residual + amount_paid_invoice_curr
                            if imp_saldo_ant > invoice.amount_total:
                                imp_saldo_ant = invoice.amount_total
                            
                            docto_relacionados.append({
                                'MonedaDR': invoice.moneda or invoice.currency_id.name,
                                'EquivalenciaDR': equivalenciadr,
                                'IdDocumento': invoice.folio_fiscal,
                                'folio_facura': invoice.number_folio or invoice.name,
                                'NumParcialidad': payment_content,
                                'ImpSaldoAnt': float_round(imp_saldo_ant, precision_digits=decimal_p, rounding_method='UP'),
                                'ImpPagado': float_round(amount_paid_invoice_curr, precision_digits=decimal_p, rounding_method='UP'),
                                'ImpSaldoInsoluto': float_round(imp_saldo_ant - amount_paid_invoice_curr, precision_digits=decimal_p, rounding_method='UP'),
                                'ObjetoImpDR': objetoimpdr,
                                'ImpuestosDR': {'traslados': trasladodr, 'retenciones': retenciondr},
                            })
                            _logger.info(f"Documento relacionado agregado: {docto_relacionados[-1]}")
                    
                    else:
                        # FLUJO ORIGINAL: Usar matched_credit_ids y matched_debit_ids
                        _logger.info("=== FLUJO ORIGINAL: Usando matched_ids ===")
                        for match_field in ('credit', 'debit'):
                            _logger.info(f"Procesando match_field: {match_field}")
                            matched_ids = pay_rec_lines[f'matched_{match_field}_ids']
                            _logger.info(f"matched_{match_field}_ids: {matched_ids}")
                        for partial in matched_ids:
                            payment_line = partial[f'{match_field}_move_id']
                            invoice_line = partial[f'{match_field}_move_id']
                            invoice_amount = partial[f'{match_field}_amount_currency']
                            invoice = invoice_line.move_id
                            decimal_p = 2

                            exchange_amount = 0
                            for exchange in partial.exchange_move_id:
                                 exchange_amount += exchange.amount_total

                            if partial.amount == 0:
                                raise UserError(
                                    "Una factura adjunta en el pago no tiene un monto liquidado por el pago. \nRevisa que todas las facturas tengan un monto pagado, puede ser necesario desvincular las facturas y vinculalas en otro orden.")

                            if not invoice.factura_cfdi:
                                continue

                            payment_content = 0
                            for widget_line in invoice.invoice_payments_widget['content']:
                                if widget_line['is_exchange'] == False:
                                   payment_content += 1 

                            if invoice.total_factura <= 0:
                                raise UserError(
                                    "No hay monto total de la factura. Carga el XML en la factura para agregar el monto total.")

                            if invoice.currency_id == payment.currency_id:
                                amount_paid_invoice_curr = invoice_amount
                                equivalenciadr = 1
                            elif invoice.currency_id == mxn_currency and invoice.currency_id != payment.currency_id:
                                amount_paid_invoice_curr = invoice_amount
                                amount_paid_invoice_comp_curr = payment_line.company_currency_id.round(
                                    payment.amount * (abs(payment_line.balance) / (paid_amount_comp_curr + exchange_amount)))
                                invoice_rate = partial.debit_amount_currency / (partial.amount  + exchange_amount)
                                exchange_rate = amount_paid_invoice_curr / amount_paid_invoice_comp_curr
                                equivalenciadr = payment.roundTraditional(exchange_rate, 6) + 0.000001
                            else:
                                amount_paid_invoice_curr = invoice_amount
                                exchange_rate = partial.debit_amount_currency / (partial.amount  + exchange_amount)
                                equivalenciadr = payment.roundTraditional(exchange_rate, 6)# + 0.000001
                            paid_pct = float_round(amount_paid_invoice_curr, precision_digits=6,
                                                   rounding_method='UP') / invoice.total_factura

                            if not invoice.tax_payment:
                                raise UserError(
                                    "No hay información de impuestos en el documento. Carga el XML en la factura para agregar los impuestos.")

                            taxes = json.loads(invoice.tax_payment)
                            objetoimpdr = '01'
                            trasladodr = []
                            retenciondr = []
                            if "translados" in taxes:
                                objetoimpdr = '02'
                                traslados = taxes['translados']
                                for traslado in traslados:
                                    basedr = float_round(float(traslado['base']) * paid_pct, precision_digits=decimal_p,
                                                         rounding_method='UP')
                                    importedr = traslado['importe'] and float_round(float(traslado['tasa']) * basedr,
                                                                                    precision_digits=decimal_p,
                                                                                    rounding_method='UP') or 0
                                    trasladodr.append({
                                        'BaseDR': payment.set_decimals(basedr, decimal_p),
                                        'ImpuestoDR': traslado['impuesto'],
                                        'TipoFactorDR': traslado['TipoFactor'],
                                        'TasaOcuotaDR': traslado['tasa'],
                                        'ImporteDR': payment.set_decimals(importedr, decimal_p) if traslado[
                                                                                                       'TipoFactor'] != 'Exento' else '',
                                    })
                                    key = traslado['tax_id']

                                    if equivalenciadr == 1:
                                        basep = basedr
                                        importep = importedr
                                    else:
                                        basep = basedr / equivalenciadr
                                        importep = importedr / equivalenciadr

                                    val = {'BaseP': basep,
                                           'ImpuestoP': traslado['impuesto'],
                                           'TipoFactorP': traslado['TipoFactor'],
                                           'TasaOCuotaP': traslado['tasa'],
                                           'ImporteP': importep, }
                                    if key not in tax_grouped_tras:
                                        tax_grouped_tras[key] = val
                                    else:
                                        tax_grouped_tras[key]['BaseP'] += basep
                                        tax_grouped_tras[key]['ImporteP'] += importep
                            if "retenciones" in taxes:
                                objetoimpdr = '02'
                                retenciones = taxes['retenciones']
                                for retencion in retenciones:
                                    basedr = float_round(float(retencion['base']) * paid_pct,
                                                         precision_digits=decimal_p, rounding_method='UP')
                                    importedr = retencion['importe'] and float_round(float(retencion['tasa']) * basedr,
                                                                                     precision_digits=decimal_p,
                                                                                     rounding_method='UP') or 0
                                    retenciondr.append({
                                        'BaseDR': payment.set_decimals(basedr, decimal_p),
                                        'ImpuestoDR': retencion['impuesto'],
                                        'TipoFactorDR': retencion['TipoFactor'],
                                        'TasaOcuotaDR': retencion['tasa'],
                                        'ImporteDR': payment.set_decimals(importedr, decimal_p),
                                    })
                                    key = retencion['tax_id']

                                    if equivalenciadr == 1:
                                        importep = importedr
                                    else:
                                        importep = importedr / equivalenciadr

                                    val = {'ImpuestoP': retencion['impuesto'],
                                           'ImporteP': importep, }
                                    if key not in tax_grouped_ret:
                                        tax_grouped_ret[key] = val
                                    else:
                                        tax_grouped_ret[key]['ImporteP'] += importep

                            #if len(payment.reconciled_invoice_ids) > 1 and payment.different_currency:
                            #    if equivalenciadr == 1:
                            #        equivalenciadr = payment.set_decimals(equivalenciadr, 10)

                            docto_relacionados.append({
                                'MonedaDR': invoice.moneda,
                                'EquivalenciaDR': equivalenciadr,
                                'IdDocumento': invoice.folio_fiscal,
                                'folio_facura': invoice.number_folio,
                                'NumParcialidad': payment_content,
                                'ImpSaldoAnt': float_round(
                                    min(invoice.amount_residual + amount_paid_invoice_curr, invoice.amount_total),
                                    precision_digits=decimal_p, rounding_method='UP'),
                                'ImpPagado': float_round(amount_paid_invoice_curr, precision_digits=decimal_p,
                                                         rounding_method='UP'),
                                'ImpSaldoInsoluto': round(float_round(
                                    min(invoice.amount_residual + amount_paid_invoice_curr, invoice.amount_total),
                                    precision_digits=decimal_p, rounding_method='UP') - \
                                                          float_round(amount_paid_invoice_curr,
                                                                      precision_digits=decimal_p, rounding_method='UP'),
                                                          2),
                                'ObjetoImpDR': objetoimpdr,
                                'ImpuestosDR': {'traslados': trasladodr, 'retenciones': retenciondr, },
                            })
                        # FIN DEL FLUJO ORIGINAL con matched_ids

                    payment.write({'docto_relacionados': json.dumps(docto_relacionados),
                                   'docto_relacionados_data': json.dumps(docto_relacionados),
                                   'retencionesp': json.dumps(tax_grouped_ret),
                                   'trasladosp': json.dumps(tax_grouped_tras), })

    def post(self):
        res = super(AccountPayment, self).post()
        for rec in self:
            #        rec.add_resitual_amounts()
            rec._onchange_payment_date()
            rec._onchange_journal()
        return res

    @api.depends('amount')
    def _compute_monto_pagar(self):
        for record in self:
            if record.amount:
                record.monto_pagar = record.amount
            else:
                record.monto_pagar = 0

    @api.depends('journal_id')
    def _compute_banco_receptor(self):
        for record in self:
            if record.journal_id and record.journal_id.bank_id:
                record.banco_receptor = record.journal_id.bank_id.name
                record.rfc_banco_receptor = record.journal_id.bank_id.bic
            else:
                record.banco_receptor = ''
                record.rfc_banco_receptor = ''
                record.cuenta_beneficiario = ''
            if record.journal_id:
                record.cuenta_beneficiario = record.journal_id.bank_acc_number
            else:
                record.banco_receptor = ''
                record.rfc_banco_receptor = ''
                record.cuenta_beneficiario = ''

    @api.depends('amount', 'currency_id')
    def _get_amount_to_text(self):
        for record in self:
            record.amount_to_text = amount_to_text_es_MX.get_amount_to_text(record, record.amount_total, 'es_cheque',
                                                                            record.currency_id.name)

    @api.model
    def _get_amount_2_text(self, amount_total):
        return amount_to_text_es_MX.get_amount_to_text(self, amount_total, 'es_cheque', self.currency_id.name)

    @api.model
    def to_json(self):
        if self.partner_id.vat == 'XAXX010101000' or self.partner_id.vat == 'XEXX010101000':
            zipreceptor = self.journal_id.codigo_postal or self.company_id.zip
        else:
            zipreceptor = self.partner_id.zip

        if self.partner_id.country_id:
           if self.partner_id.country_id.code != 'MX':
              zipreceptor = self.journal_id.codigo_postal or self.company_id.zip
        else:
           raise UserError(_('El receptor no tiene un país configurado.'))

        #no_decimales = self.currency_id.no_decimales
        no_decimales_tc = self.currency_id.no_decimales_tc

        self.monedap = self.currency_id.name
        if self.currency_id.name == 'MXN':
            self.tipocambiop = '1'
        else:
            self.tipocambiop = self.set_decimals(1 / self.currency_id.with_context(date=self.date).rate,
                                                 no_decimales_tc)

        timezone = self._context.get('tz')
        if not timezone:
            timezone = self.env.user.partner_id.tz or 'America/Mexico_City'
        # timezone = tools.ustr(timezone).encode('utf-8')

        if not self.fecha_pago:
            raise UserError(_('Falta configurar fecha de pago en la sección de CFDI del documento.'))
        else:
            local = pytz.timezone(timezone)
            naive_from = self.fecha_pago
            local_dt_from = naive_from.replace(tzinfo=pytz.UTC).astimezone(local)
            date_from = local_dt_from.strftime("%Y-%m-%dT%H:%M:%S")
        self.add_resitual_amounts()

        # corregir hora
        local2 = pytz.timezone(timezone)
        if not self.date_payment:
            naive_from2 = datetime.now()
        else:
            naive_from2 = self.date_payment
        local_dt_from2 = naive_from2.replace(tzinfo=pytz.UTC).astimezone(local2)
        date_cfdi = local_dt_from2.strftime("%Y-%m-%dT%H:%M:%S")
        if not self.date_payment:
            self.date_payment = datetime.now()

        self.check_cfdi_values()

        conceptos = []
        conceptos.append({
            'ClaveProdServ': '84111506',
            'ClaveUnidad': 'ACT',
            'cantidad': 1,
            'descripcion': 'Pago',
            'valorunitario': '0',
            'importe': '0',
            'ObjetoImp': '01',
        })

        taxes_traslado = json.loads(self.trasladosp)
        taxes_retenciones = json.loads(self.retencionesp)
        impuestosp = {}
        totales = {}
        self.total_pago = 0
        if taxes_traslado or taxes_retenciones:
            retencionp = []
            trasladop = []
            if taxes_traslado:
                for line in taxes_traslado.values():
                    trasladop.append({'ImpuestoP': line['ImpuestoP'],
                                      'TipoFactorP': line['TipoFactorP'],
                                      'TasaOCuotaP': line['TasaOCuotaP'],
                                      'ImporteP': self.roundTraditional(line['ImporteP'], 2) if line['TipoFactorP'] != 'Exento' else '',
                                      'BaseP': self.roundTraditional(line['BaseP'], 2),
                                      })
                    if line['ImpuestoP'] == '002' and line['TasaOCuotaP'] == '0.160000':
                        totales.update({'TotalTrasladosBaseIVA16': self.selectRoundseparate(
                            line['BaseP'] * float(self.tipocambiop), 2, self.redondeo_t_base),
                                        'TotalTrasladosImpuestoIVA16': self.selectRoundseparate(
                                            line['ImporteP'] * float(self.tipocambiop),2, self.redondeo_t_impuesto),})
                    if line['ImpuestoP'] == '002' and line['TasaOCuotaP'] == '0.080000':
                        totales.update({'TotalTrasladosBaseIVA8': self.roundTraditional(
                            line['BaseP'] * float(self.tipocambiop), 2),
                                        'TotalTrasladosImpuestoIVA8': self.roundTraditional(
                                            line['ImporteP'] * float(self.tipocambiop), 2), })
                    if line['ImpuestoP'] == '002' and line['TasaOCuotaP'] == '0.000000':
                        totales.update({'TotalTrasladosBaseIVA0': self.roundTraditional(
                            line['BaseP'] * float(self.tipocambiop), 2),
                                        'TotalTrasladosImpuestoIVA0': self.roundTraditional(
                                            line['ImporteP'] * float(self.tipocambiop), 2), })
                    if line['ImpuestoP'] == '002' and line['TipoFactorP'] == 'Exento':
                        totales.update({'TotalTrasladosBaseIVAExento': self.roundTraditional(
                            line['BaseP'] * float(self.tipocambiop), 2), })
                    if line['TipoFactorP'] != 'Exento':
                        self.total_pago += round(line['BaseP'] * float(self.tipocambiop), 2) + round(
                            line['ImporteP'] * float(self.tipocambiop), 2)
                    else:
                        self.total_pago += round(line['BaseP'] * float(self.tipocambiop), 2)
                impuestosp.update({'TrasladosP': trasladop})
            if taxes_retenciones:
                for line in taxes_retenciones.values():
                    retencionp.append({'ImpuestoP': line['ImpuestoP'],
                                       'ImporteP': self.set_decimals(line['ImporteP'], 2),
                                       })
                    if line['ImpuestoP'] == '002':
                        totales.update({'TotalRetencionesIVA': self.roundTraditional(
                            line['ImporteP'] * float(self.tipocambiop), 2), })
                    if line['ImpuestoP'] == '001':
                        totales.update({'TotalRetencionesISR': self.roundTraditional(
                            line['ImporteP'] * float(self.tipocambiop), 2), })
                    if line['ImpuestoP'] == '003':
                        totales.update({'TotalRetencionesIEPS': self.roundTraditional(
                            line['ImporteP'] * float(self.tipocambiop), 2), })
                    self.total_pago -= round(line['ImporteP'] * float(self.tipocambiop), 2)
                impuestosp.update({'RetencionesP': retencionp})
        totales.update({'MontoTotalPagos': self.set_decimals(self.amount,2) 
                                           if self.monedap == 'MXN' 
                                           else self.selectRoundseparate(self.amount * float(self.tipocambiop), 2, self.redondeo_t_total), })
        # totales.update({'MontoTotalPagos': self.set_decimals(self.total_pago, 2),})

        pagos = []
        pagos.append({
            'FechaPago': date_from,
            'FormaDePagoP': self.forma_pago_id.code,
            'MonedaP': self.monedap,
            'TipoCambioP': self.tipocambiop,  # if self.monedap != 'MXN' else '1',
            'Monto': self.set_decimals(self.amount, 2),
            # 'Monto':  self.set_decimals(self.total_pago/float(self.tipocambiop), 2),
            'NumOperacion': self.numero_operacion,

            'RfcEmisorCtaOrd': self.rfc_banco_emisor if self.forma_pago_id.code in ['02', '03', '04', '05', '28',
                                                                                    '29'] else '',
            'NomBancoOrdExt': self.banco_emisor if self.forma_pago_id.code in ['02', '03', '04', '05', '28',
                                                                               '29'] else '',
            'CtaOrdenante': self.cuenta_emisor.acc_number if self.cuenta_emisor and self.forma_pago_id.code in ['02',
                                                                                                                '03',
                                                                                                                '04',
                                                                                                                '05',
                                                                                                                '28',
                                                                                                                '29'] else '',
            'RfcEmisorCtaBen': self.rfc_banco_receptor if self.forma_pago_id.code in ['02', '03', '04', '05', '28',
                                                                                      '29'] else '',
            'CtaBeneficiario': self.cuenta_beneficiario if self.forma_pago_id.code in ['02', '03', '04', '05', '28',
                                                                                       '29'] else '',
            'DoctoRelacionado': json.loads(self.docto_relacionados),
            'ImpuestosP': impuestosp,
        })

        if self.reconciled_invoice_ids:
            request_params = {
                'factura': {
                    'serie': str(re.sub(r'[0-9]+', '', self.name)).replace('/', '').replace('.', ''),
                    'folio': str(re.sub('[^0-9]','', self.name)),
                    'fecha_expedicion': date_cfdi,
                    'subtotal': '0',
                    'moneda': 'XXX',
                    'total': '0',
                    'tipocomprobante': 'P',
                    'LugarExpedicion': self.journal_id.codigo_postal or self.company_id.zip,
                    'confirmacion': self.confirmacion,
                    'Exportacion': '01',
                },
                'emisor': {
                    'rfc': self.company_id.vat.upper(),
                    'nombre': self.company_id.nombre_fiscal.upper(),
                    'RegimenFiscal': self.company_id.regimen_fiscal_id.code,
                },
                'receptor': {
                    'nombre': self.partner_id.name.upper(),
                    'rfc': self.partner_id.vat.upper() if self.partner_id.country_id.code == 'MX' else 'XEXX010101000',
                    'ResidenciaFiscal': self.partner_id.country_id.codigo_mx if self.partner_id.country_id.code != 'MX' else '',
                    'NumRegIdTrib': self.partner_id.vat.upper() if self.partner_id.country_id.code != 'MX' else '',
                    'UsoCFDI': 'CP01',
                    'RegimenFiscalReceptor': self.partner_id.regimen_fiscal_id.code,
                    'DomicilioFiscalReceptor': zipreceptor,
                },

                'informacion': {
                    'cfdi': '4.0',
                    'sistema': 'odoo18',
                    'version': '2',
                    'api_key': self.company_id.proveedor_timbrado,
                    'modo_prueba': self.company_id.modo_prueba,
                },

                'conceptos': conceptos,

                'totales': totales,

                'pagos20': {'Pagos': pagos},

            }

            if self.uuid_relacionado:
                cfdi_relacionado = []
                uuids = self.uuid_relacionado.replace(' ', '').split(',')
                for uuid in uuids:
                    cfdi_relacionado.append({
                        'uuid': uuid,
                    })
                request_params.update(
                    {'CfdisRelacionados': {'UUID': cfdi_relacionado, 'TipoRelacion': self.tipo_relacion}})

        else:
            raise UserError(
                _('No tiene ninguna factura ligada al documento de pago, debe al menos tener una factura ligada. \n Desde la factura crea el pago para que se asocie la factura al pago.'))
        return request_params

    def check_cfdi_values(self):
        if not self.company_id.vat:
            raise UserError(_('El emisor no tiene RFC configurado.'))
        if not self.company_id.name:
            raise UserError(_('El emisor no tiene nombre configurado.'))
        if not self.partner_id.vat:
            raise UserError(_('El receptor no tiene RFC configurado.'))
        if not self.company_id.regimen_fiscal_id:
            raise UserError(_('El emisor no régimen fiscal configurado.'))
        if not self.journal_id.codigo_postal and not self.company_id.zip:
            raise UserError(_('El emisor no tiene código postal configurado.'))
        if not self.forma_pago_id:
            raise UserError(_('Falta configurar la forma de pago.'))

    def set_decimals(self, amount, precision):
        if amount is None or amount is False:
            return None
        return '%.*f' % (precision, amount)

    def roundTraditional(self, val, digits):
       if val != 0:
          return round(val + 10 ** (-len(str(val)) - 1), digits)
       else:
          return 0

    def trunc(self, val, digits):
       if val != 0:
          x = 10 ** digits
          return int(val*x)/(x)
       else:
          return 0

    def selectRoundseparate(self, val, digits, r_option):
       if r_option == '01':
           return self.roundTraditional(val, digits)
       elif r_option == '02':
           return self.set_decimals(val, digits)
       elif r_option == '03':
           return math.ceil(val*100)/100
       else:
           return self.trunc(val, digits)

    def clean_text(self, text):
        clean_text = text.replace('\n', ' ').replace('\\', ' ').replace('-', ' ').replace('/', ' ').replace('|', ' ')
        clean_text = clean_text.replace(',', ' ').replace(';', ' ').replace('>', ' ').replace('<', ' ')
        return clean_text[:1000]

    def to_json_techbythree(self):
        """Genera JSON en formato TechByThree para complemento de pago"""
        if self.partner_id.vat == 'XAXX010101000' or self.partner_id.vat == 'XEXX010101000':
            zipreceptor = self.journal_id.codigo_postal or self.company_id.zip
        else:
            zipreceptor = self.partner_id.zip

        if self.partner_id.country_id:
           if self.partner_id.country_id.code != 'MX':
              zipreceptor = self.journal_id.codigo_postal or self.company_id.zip
        else:
           raise UserError(_('El receptor no tiene un país configurado.'))

        timezone = self._context.get('tz')
        if not timezone:
            timezone = self.env.user.partner_id.tz or 'America/Mexico_City'

        if not self.fecha_pago:
            raise UserError(_('Falta configurar fecha de pago en la sección de CFDI del documento.'))
        else:
            local = pytz.timezone(timezone)
            naive_from = self.fecha_pago
            local_dt_from = naive_from.replace(tzinfo=pytz.UTC).astimezone(local)
            date_from = local_dt_from.strftime("%Y-%m-%dT%H:%M:%S")  # fecha_pago usa formato ISO

        local2 = pytz.timezone(timezone)
        if not self.date_payment:
            naive_from2 = datetime.now()
        else:
            naive_from2 = self.date_payment
        local_dt_from2 = naive_from2.replace(tzinfo=pytz.UTC).astimezone(local2)
        date_cfdi = local_dt_from2.strftime("%Y-%m-%d %H:%M:%S")  # fecha_emision usa formato con espacio
        if not self.date_payment:
            self.date_payment = datetime.now()

        self.check_cfdi_values()
        self.add_resitual_amounts()

        # Verificar que haya facturas relacionadas
        if not self.reconciled_invoice_ids:
            raise UserError(_('No tiene ninguna factura ligada al documento de pago. Debe tener al menos una factura ligada.\nDesde la factura crea el pago para que se asocie la factura al pago.'))

        self.monedap = self.currency_id.name
        if self.currency_id.name == 'MXN':
            self.tipocambiop = 1
        else:
            no_decimales_tc = self.currency_id.no_decimales_tc
            self.tipocambiop = float(self.set_decimals(1 / self.currency_id.with_context(date=self.date).rate, no_decimales_tc))

        # Construir complemento pagos_20
        docto_relacionado = []
        _logger.info(f"DEBUG: self.docto_relacionados = {self.docto_relacionados}")
        if self.docto_relacionados:
            doctos = json.loads(self.docto_relacionados)
            _logger.info(f"DEBUG: doctos parseados = {doctos}")
            for doc in doctos:
                docto_dict = {
                    'id_documento': doc.get('IdDocumento'),
                    'moneda_dr': doc.get('MonedaDR'),
                    'num_parcialidad': doc.get('NumParcialidad'),
                    'imp_saldo_ant': float(doc.get('ImpSaldoAnt', 0)),
                    'imp_pagado': float(doc.get('ImpPagado', 0)),
                    'imp_saldo_insoluto': float(doc.get('ImpSaldoInsoluto', 0)),
                    'objeto_imp_dr': doc.get('ObjetoImpDR', '01'),
                }
                if doc.get('EquivalenciaDR'):
                    docto_dict['equivalencia_dr'] = float(doc.get('EquivalenciaDR'))
                
                # Intentar con nomenclatura snake_case completa para TechByThree
                objeto_imp = doc.get('ObjetoImpDR', '01')
                if objeto_imp == '02' and doc.get('ImpuestosDR'):
                    _logger.info(f"DEBUG: ObjetoImpDR es 02, convirtiendo a snake_case completo")
                    imp_dr_original = doc.get('ImpuestosDR', {})
                    _logger.info(f"DEBUG: ImpuestosDR original = {imp_dr_original}")
                    
                    # Construir impuestos_dr con nomenclatura snake_case completa
                    impuestos_dr = {}
                    
                    # Transformar traslados a snake_case
                    traslados = imp_dr_original.get('traslados', imp_dr_original.get('TrasladosDR', []))
                    if traslados:
                        traslados_snake = []
                        for tras in traslados:
                            tras_dict = {
                                'base_dr': tras.get('BaseDR', tras.get('base_dr')),
                                'impuesto_dr': tras.get('ImpuestoDR', tras.get('impuesto_dr')),
                                'tipo_factor_dr': tras.get('TipoFactorDR', tras.get('tipo_factor_dr')),
                                'tasa_o_cuota_dr': tras.get('TasaOCuotaDR', tras.get('TasaOcuotaDR', tras.get('tasa_o_cuota_dr'))),
                            }
                            # importe_dr es opcional
                            importe = tras.get('ImporteDR', tras.get('importe_dr'))
                            if importe and str(importe).strip():
                                tras_dict['importe_dr'] = importe
                            traslados_snake.append(tras_dict)
                        impuestos_dr['traslados_dr'] = traslados_snake
                    
                    # Transformar retenciones a snake_case
                    retenciones = imp_dr_original.get('retenciones', imp_dr_original.get('RetencionesDR', []))
                    if retenciones:
                        retenciones_snake = []
                        for ret in retenciones:
                            ret_dict = {
                                'base_dr': ret.get('BaseDR', ret.get('base_dr')),
                                'impuesto_dr': ret.get('ImpuestoDR', ret.get('impuesto_dr')),
                                'tipo_factor_dr': ret.get('TipoFactorDR', ret.get('tipo_factor_dr')),
                                'tasa_o_cuota_dr': ret.get('TasaOCuotaDR', ret.get('TasaOCuotaDR', ret.get('tasa_o_cuota_dr'))),
                                'importe_dr': ret.get('ImporteDR', ret.get('importe_dr')),
                            }
                            retenciones_snake.append(ret_dict)
                        impuestos_dr['retenciones_dr'] = retenciones_snake
                    
                    if impuestos_dr:
                        docto_dict['impuestos_dr'] = impuestos_dr
                        _logger.info(f"DEBUG: impuestos_dr final (snake_case completo) = {docto_dict['impuestos_dr']}")
                
                docto_relacionado.append(docto_dict)
        
        _logger.info(f"DEBUG: docto_relacionado final = {docto_relacionado}")

        pago = {
            'fecha_pago': date_from,
            'forma_de_pago_p': self.forma_pago_id.code,
            'moneda_p': self.monedap,
            'monto': float(self.set_decimals(self.amount, 2)),
            'docto_relacionado': docto_relacionado,  # Siempre incluir, aunque esté vacío
        }
        
        # TechByThree requiere tipo_cambio_p siempre presente
        if self.monedap == 'MXN':
            pago['tipo_cambio_p'] = 1  # Sin decimales para MXN
        else:
            pago['tipo_cambio_p'] = float(self.tipocambiop)
            
        if self.numero_operacion:
            pago['num_operacion'] = self.numero_operacion

        # Construir el JSON principal
        request_params = {
            'fecha_emision': date_cfdi,
            'serie': str(re.sub(r'[0-9]+', '', self.name)).replace('/', '').replace('.', ''),
            'folio': int(re.sub('[^0-9]','', self.name)) if re.sub('[^0-9]','', self.name) else 1,
            'moneda': 'XXX',
            'lugar_expedicion': self.journal_id.codigo_postal or self.company_id.zip,
            'tipo_comprobante': 'P',
            'subtotal': 0,
            'total': 0,
            'exportacion': '01',
            'emisor': {
                'rfc': self.company_id.vat.upper(),
                'razon_social': self.company_id.nombre_fiscal.upper(),
                'regimen_fiscal': self.company_id.regimen_fiscal_id.code,
                'codigo_postal': self.journal_id.codigo_postal or self.company_id.zip,
            },
            'receptor': {
                'rfc': self.partner_id.vat.upper() if self.partner_id.country_id.code == 'MX' else 'XEXX010101000',
                'razon_social': self.partner_id.name.upper(),
                'uso_cfdi': 'CP01',
                'regimen_fiscal': self.partner_id.regimen_fiscal_id.code,
                'codigo_postal': zipreceptor,
            },
            'conceptos': [
                {
                    'clave_prod_serv': '84111506',
                    'descripcion': 'Pago',
                    'clave_unidad': 'ACT',
                    'valor_unitario': 0,
                    'cantidad': 1,
                    'subtotal': 0,
                    'importe': 0,
                    'objeto_impuesto': '01',
                }
            ],
            'complementos': {
                'pagos_20': {
                    'version': '2.0',
                    'totales': {
                        'monto_total_pagos': float(self.set_decimals(self.amount, 2)),
                    },
                    'pago': [pago],
                }
            }
        }
        
        _logger.info("=== JSON FINAL PARA TECHBYTHREE ===")
        _logger.info(f"Pago completo: {json.dumps(request_params['complementos']['pagos_20']['pago'][0], indent=2)}")

        return request_params

    def to_xml_techbythree(self):
        """Genera XML en formato CFDI 4.0 para TimbradoXml de TechByThree"""
        if self.partner_id.vat == 'XAXX010101000' or self.partner_id.vat == 'XEXX010101000':
            zipreceptor = self.journal_id.codigo_postal or self.company_id.zip
        else:
            zipreceptor = self.partner_id.zip

        if self.partner_id.country_id:
            if self.partner_id.country_id.code != 'MX':
                zipreceptor = self.journal_id.codigo_postal or self.company_id.zip
        else:
            raise UserError(_('El receptor no tiene un país configurado.'))

        timezone = self._context.get('tz')
        if not timezone:
            timezone = self.env.user.partner_id.tz or 'America/Mexico_City'

        if not self.fecha_pago:
            raise UserError(_('Falta configurar fecha de pago en la sección de CFDI del documento.'))
        else:
            local = pytz.timezone(timezone)
            naive_from = self.fecha_pago
            local_dt_from = naive_from.replace(tzinfo=pytz.UTC).astimezone(local)
            date_from = local_dt_from.strftime("%Y-%m-%dT%H:%M:%S")

        local2 = pytz.timezone(timezone)
        if not self.date_payment:
            naive_from2 = datetime.now()
        else:
            naive_from2 = self.date_payment
        local_dt_from2 = naive_from2.replace(tzinfo=pytz.UTC).astimezone(local2)
        date_cfdi = local_dt_from2.strftime("%Y-%m-%dT%H:%M:%S")
        if not self.date_payment:
            self.date_payment = datetime.now()

        self.check_cfdi_values()

        # Namespaces
        NSMAP = {
            'cfdi': 'http://www.sat.gob.mx/cfd/4',
            'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
            'pago20': 'http://www.sat.gob.mx/Pagos20'
        }

        # Crear elemento raíz Comprobante
        comprobante = etree.Element(
            '{http://www.sat.gob.mx/cfd/4}Comprobante',
            nsmap=NSMAP,
            attrib={
                '{http://www.w3.org/2001/XMLSchema-instance}schemaLocation': 
                    'http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd '
                    'http://www.sat.gob.mx/Pagos20 http://www.sat.gob.mx/sitio_internet/cfd/Pagos/Pagos20.xsd',
                'Version': '4.0',
                'Serie': str(re.sub(r'[0-9]+', '', self.name)).replace('/', '').replace('.', ''),
                'Folio': str(int(re.sub('[^0-9]','', self.name)) if re.sub('[^0-9]','', self.name) else 1),
                'Fecha': date_cfdi,
                'Sello': '',
                'NoCertificado': '',
                'Certificado': '',
                'SubTotal': '0',
                'Moneda': 'XXX',
                'Total': '0',
                'TipoDeComprobante': 'P',
                'Exportacion': '01',
                'LugarExpedicion': self.journal_id.codigo_postal or self.company_id.zip,
            }
        )

        # Emisor
        emisor = etree.SubElement(comprobante, '{http://www.sat.gob.mx/cfd/4}Emisor')
        emisor.set('Rfc', self.company_id.vat.upper())
        emisor.set('Nombre', self.company_id.nombre_fiscal.upper())
        emisor.set('RegimenFiscal', self.company_id.regimen_fiscal_id.code)

        # Receptor
        receptor = etree.SubElement(comprobante, '{http://www.sat.gob.mx/cfd/4}Receptor')
        receptor.set('Rfc', self.partner_id.vat.upper() if self.partner_id.country_id.code == 'MX' else 'XEXX010101000')
        receptor.set('Nombre', self.partner_id.name.upper())
        receptor.set('DomicilioFiscalReceptor', zipreceptor)
        receptor.set('RegimenFiscalReceptor', self.partner_id.regimen_fiscal_id.code)
        receptor.set('UsoCFDI', 'CP01')

        # Conceptos
        conceptos = etree.SubElement(comprobante, '{http://www.sat.gob.mx/cfd/4}Conceptos')
        concepto = etree.SubElement(conceptos, '{http://www.sat.gob.mx/cfd/4}Concepto')
        concepto.set('ClaveProdServ', '84111506')
        concepto.set('Cantidad', '1')
        concepto.set('ClaveUnidad', 'ACT')
        concepto.set('Descripcion', 'Pago')
        concepto.set('ValorUnitario', '0')
        concepto.set('Importe', '0')
        concepto.set('ObjetoImp', '01')

        # Complemento
        complemento = etree.SubElement(comprobante, '{http://www.sat.gob.mx/cfd/4}Complemento')
        
        # Pagos
        pagos = etree.SubElement(complemento, '{http://www.sat.gob.mx/Pagos20}Pagos')
        pagos.set('Version', '2.0')

        # DoctoRelacionados obtenidos de add_resitual_amounts
        self.add_resitual_amounts()
        
        if not self.docto_relacionados_data:
            raise UserError(_('No hay documentos relacionados. Ejecute add_resitual_amounts primero.'))

        doctos_data = ast.literal_eval(self.docto_relacionados_data) if isinstance(self.docto_relacionados_data, str) else self.docto_relacionados_data

        # Calcular totales de impuestos para Totales
        total_traslados_base_iva16 = 0
        total_traslados_impuesto_iva16 = 0
        total_retenciones_iva = 0
        total_retenciones_isr = 0
        
        for docto in doctos_data:
            if docto.get('ObjetoImpDR') == '02' and docto.get('ImpuestosDR'):
                traslados_key = 'TrasladosDR' if 'TrasladosDR' in docto['ImpuestosDR'] else 'traslados'
                if docto['ImpuestosDR'].get(traslados_key):
                    for tras in docto['ImpuestosDR'][traslados_key]:
                        if tras.get('ImpuestoDR', tras.get('impuesto')) == '002':  # IVA
                            total_traslados_base_iva16 += float(tras.get('BaseDR', tras.get('base', 0)))
                            total_traslados_impuesto_iva16 += float(tras.get('ImporteDR', tras.get('importe', 0)))
                
                retenciones_key = 'RetencionesDR' if 'RetencionesDR' in docto['ImpuestosDR'] else 'retenciones'
                if docto['ImpuestosDR'].get(retenciones_key):
                    for ret in docto['ImpuestosDR'][retenciones_key]:
                        impuesto = ret.get('ImpuestoDR', ret.get('impuesto'))
                        if impuesto == '002':  # IVA
                            total_retenciones_iva += float(ret.get('ImporteDR', ret.get('importe', 0)))
                        elif impuesto == '001':  # ISR
                            total_retenciones_isr += float(ret.get('ImporteDR', ret.get('importe', 0)))

        # Totales
        totales = etree.SubElement(pagos, '{http://www.sat.gob.mx/Pagos20}Totales')
        totales.set('MontoTotalPagos', self.set_decimals(self.amount, 2))
        
        if total_traslados_base_iva16 > 0:
            totales.set('TotalTrasladosBaseIVA16', self.set_decimals(total_traslados_base_iva16, 2))
            totales.set('TotalTrasladosImpuestoIVA16', self.set_decimals(total_traslados_impuesto_iva16, 2))
        
        if total_retenciones_iva > 0:
            totales.set('TotalRetencionesIVA', self.set_decimals(total_retenciones_iva, 2))
        
        if total_retenciones_isr > 0:
            totales.set('TotalRetencionesISR', self.set_decimals(total_retenciones_isr, 2))

        # Pago
        pago = etree.SubElement(pagos, '{http://www.sat.gob.mx/Pagos20}Pago')
        pago.set('FechaPago', date_from)
        pago.set('FormaDePagoP', self.forma_pago_id.code)
        pago.set('MonedaP', self.currency_id.name)
        pago.set('Monto', self.set_decimals(self.amount, 2))
        
        # TipoCambioP: Siempre incluir, valor "1" para MXN según validación de TechByThree
        if self.currency_id.name != 'MXN':
            tipo_cambio = self.manual_exchange_rate if self.manual_exchange_rate else self.company_id.currency_id._convert(
                1, self.currency_id, self.company_id, self.date_payment or fields.Date.today())
            pago.set('TipoCambioP', self.set_decimals(tipo_cambio, 6))
        else:
            # Para MXN, TechByThree requiere explícitamente "1"
            pago.set('TipoCambioP', '1')

        # DoctoRelacionados (doctos_data ya fue calculado arriba en Totales)
        for docto in doctos_data:
            dr = etree.SubElement(pago, '{http://www.sat.gob.mx/Pagos20}DoctoRelacionado')
            dr.set('IdDocumento', str(docto.get('IdDocumento', '')))
            dr.set('MonedaDR', str(docto.get('MonedaDR', 'MXN')))
            dr.set('NumParcialidad', str(docto.get('NumParcialidad', '1')))
            dr.set('ImpSaldoAnt', str(docto.get('ImpSaldoAnt', '0')))
            dr.set('ImpPagado', str(docto.get('ImpPagado', '0')))
            dr.set('ImpSaldoInsoluto', str(docto.get('ImpSaldoInsoluto', '0')))
            dr.set('ObjetoImpDR', str(docto.get('ObjetoImpDR', '01')))
            
            if docto.get('EquivalenciaDR'):
                dr.set('EquivalenciaDR', str(docto['EquivalenciaDR']))

            # Si tiene impuestos (ObjetoImpDR = '02')
            if docto.get('ObjetoImpDR') == '02' and docto.get('ImpuestosDR'):
                impuestos_dr = etree.SubElement(dr, '{http://www.sat.gob.mx/Pagos20}ImpuestosDR')
                
                # Traslados
                traslados_key = 'TrasladosDR' if 'TrasladosDR' in docto['ImpuestosDR'] else 'traslados'
                if docto['ImpuestosDR'].get(traslados_key):
                    traslados_dr_container = etree.SubElement(impuestos_dr, '{http://www.sat.gob.mx/Pagos20}TrasladosDR')
                    for tras in docto['ImpuestosDR'][traslados_key]:
                        traslado_dr = etree.SubElement(traslados_dr_container, '{http://www.sat.gob.mx/Pagos20}TrasladoDR')
                        traslado_dr.set('BaseDR', str(tras.get('BaseDR', '0')))
                        traslado_dr.set('ImpuestoDR', str(tras.get('ImpuestoDR', '002')))
                        traslado_dr.set('TipoFactorDR', str(tras.get('TipoFactorDR', 'Tasa')))
                        # Soportar ambas variantes: TasaOCuotaDR y TasaOcuotaDR (typo en add_resitual_amounts)
                        tasa = tras.get('TasaOCuotaDR', tras.get('TasaOcuotaDR', '0.160000'))
                        traslado_dr.set('TasaOCuotaDR', str(tasa))
                        traslado_dr.set('ImporteDR', str(tras.get('ImporteDR', '0')))
                
                # Retenciones
                retenciones_key = 'RetencionesDR' if 'RetencionesDR' in docto['ImpuestosDR'] else 'retenciones'
                if docto['ImpuestosDR'].get(retenciones_key):
                    retenciones_dr_container = etree.SubElement(impuestos_dr, '{http://www.sat.gob.mx/Pagos20}RetencionesDR')
                    for ret in docto['ImpuestosDR'][retenciones_key]:
                        retencion_dr = etree.SubElement(retenciones_dr_container, '{http://www.sat.gob.mx/Pagos20}RetencionDR')
                        retencion_dr.set('BaseDR', str(ret.get('BaseDR', '0')))
                        retencion_dr.set('ImpuestoDR', str(ret.get('ImpuestoDR', '002')))
                        retencion_dr.set('TipoFactorDR', str(ret.get('TipoFactorDR', 'Tasa')))
                        # Soportar ambas variantes: TasaOCuotaDR y TasaOcuotaDR (typo en add_resitual_amounts)
                        tasa = ret.get('TasaOCuotaDR', ret.get('TasaOcuotaDR', '0.160000'))
                        retencion_dr.set('TasaOCuotaDR', str(tasa))
                        retencion_dr.set('ImporteDR', str(ret.get('ImporteDR', '0')))

        # ImpuestosP (impuestos a nivel del pago, requeridos según validación de TechByThree)
        if total_traslados_impuesto_iva16 > 0 or total_retenciones_iva > 0 or total_retenciones_isr > 0:
            impuestos_p = etree.SubElement(pago, '{http://www.sat.gob.mx/Pagos20}ImpuestosP')
            
            # TrasladosP
            if total_traslados_impuesto_iva16 > 0:
                traslados_p_container = etree.SubElement(impuestos_p, '{http://www.sat.gob.mx/Pagos20}TrasladosP')
                traslado_p = etree.SubElement(traslados_p_container, '{http://www.sat.gob.mx/Pagos20}TrasladoP')
                traslado_p.set('BaseP', self.set_decimals(total_traslados_base_iva16, 2))
                traslado_p.set('ImpuestoP', '002')  # IVA
                traslado_p.set('TipoFactorP', 'Tasa')
                traslado_p.set('TasaOCuotaP', '0.160000')
                traslado_p.set('ImporteP', self.set_decimals(total_traslados_impuesto_iva16, 2))
            
            # RetencionesP
            if total_retenciones_iva > 0 or total_retenciones_isr > 0:
                retenciones_p_container = etree.SubElement(impuestos_p, '{http://www.sat.gob.mx/Pagos20}RetencionesP')
                
                if total_retenciones_isr > 0:
                    retencion_p = etree.SubElement(retenciones_p_container, '{http://www.sat.gob.mx/Pagos20}RetencionP')
                    retencion_p.set('ImpuestoP', '001')  # ISR
                    retencion_p.set('ImporteP', self.set_decimals(total_retenciones_isr, 2))
                
                if total_retenciones_iva > 0:
                    retencion_p = etree.SubElement(retenciones_p_container, '{http://www.sat.gob.mx/Pagos20}RetencionP')
                    retencion_p.set('ImpuestoP', '002')  # IVA
                    retencion_p.set('ImporteP', self.set_decimals(total_retenciones_iva, 2))

        # Convertir a string XML
        xml_string = etree.tostring(comprobante, pretty_print=True, xml_declaration=True, encoding='UTF-8')
        
        _logger.info("=== XML GENERADO PARA TECHBYTHREE ===")
        _logger.info(xml_string.decode('utf-8'))
        
        return xml_string.decode('utf-8')

    def complete_payment(self):
        for p in self:
            _logger.info(f"=== INICIO complete_payment para pago {p.name} ===")
            _logger.info(f"Folio fiscal actual: {p.folio_fiscal}")
            _logger.info(f"Estado pago actual: {p.estado_pago}")
            _logger.info(f"Proveedor timbrado: {p.company_id.proveedor_timbrado}")
            
            if p.folio_fiscal:
                _logger.info("Pago ya tiene folio fiscal, marcando como pago_correcto")
                p.write({'estado_pago': 'pago_correcto'})
                return True

            # Generar datos según el proveedor
            if p.company_id.proveedor_timbrado == 'techbythree':
                # TechByThree: Generar XML para endpoint TimbraCFDI
                xml_content = p.to_xml_techbythree()
                # Codificar XML en base64 (requerido por TechByThree)
                xml_base64 = base64.b64encode(xml_content.encode('utf-8')).decode('utf-8')
                # Formato correcto según documentación Postman de TechByThree
                values = {
                    'XmlComprobanteBase64': xml_base64,
                    'IdComprobante': p.name.replace('/', '_').replace('.', '_')
                }
                
                base_url = p.company_id.techbythree_url_base or 'https://dev.techbythree.com/api'
                if base_url.endswith('/api'):
                    base_url = base_url[:-4]
                base_url = base_url.rstrip('/')
                
                client_id = p.company_id.techbythree_user
                url = '%s/api/v1/compatibilidad/%s/TimbraCFDI' % (base_url, client_id)
                
                headers = {
                    'Content-type': 'application/json',
                    'Accept': 'application/json',
                    'Authorization': 'Bearer %s' % p.company_id.techbythree_password,
                    'X-CLIENT-ID': client_id
                }
            else:
                values = p.to_json()
                headers = {"Content-type": "application/json"}
            
            if p.company_id.proveedor_timbrado == 'servidor':
                url = '%s' % ('https://facturacion.itadmin.com.mx/api/payment')
            elif p.company_id.proveedor_timbrado == 'servidor2':
                url = '%s' % ('https://facturacion2.itadmin.com.mx/api/payment')
            elif p.company_id.proveedor_timbrado != 'techbythree':
                raise UserError(_('Error, falta seleccionar el servidor de timbrado en la configuración de la compañía.'))

            try:
                _logger.info("=== COMPLEMENTO DE PAGO ===")
                _logger.info(f"Proveedor: {p.company_id.proveedor_timbrado}")
                _logger.info(f"URL: {url}")
                _logger.info(f"Headers: {headers}")
                if p.company_id.proveedor_timbrado == 'techbythree':
                    _logger.info(f"Tipo de datos: XML")
                    _logger.info(f"XML enviado (primeros 1000 chars): {xml_content[:1000]}")
                    _logger.info(f"XML BASE64 (primeros 100 chars): {xml_base64[:100]}")
                    _logger.info(f"JSON enviado: {json.dumps(values)[:200]}")
                else:
                    _logger.info(f"Datos enviados: {json.dumps(values, indent=2)}")
                
                response = requests.post(url,
                                         auth=None, data=json.dumps(values),
                                         headers=headers)
                
                _logger.info(f"Response status: {response.status_code}")
                _logger.info(f"Response content: {response.text[:2000]}")
                _logger.info(f"Response headers: {response.headers}")
            except Exception as e:
                error = str(e)
                if "Name or service not known" in error or "Failed to establish a new connection" in error:
                    raise UserError(_('Servidor fuera de servicio, favor de intentar mas tarde'))
                else:
                    raise UserError(_(error))

            if "Whoops, looks like something went wrong." in response.text:
                raise UserError(
                    _('Error en el proceso de timbrado, espere un minuto y vuelva a intentar timbrar nuevamente. \nSi el error aparece varias veces reportarlo con la persona de sistemas.'))
            
            # Intentar parsear JSON con manejo de errores
            try:
                json_response = response.json()
                _logger.info(f"JSON response parseado correctamente: {json.dumps(json_response, indent=2)}")
            except ValueError as e:
                _logger.error(f"Error parsing JSON response. Status: {response.status_code}, Content: {response.text[:500]}")
                raise UserError(
                    _('Error al procesar la respuesta del PAC.\nStatus Code: %s\nRespuesta: %s') % (
                        response.status_code, 
                        response.text[:200] if response.text else 'Vacía'
                    ))
            
            xml_file_link = False
            
            # Procesar respuesta según el proveedor
            if p.company_id.proveedor_timbrado == 'techbythree':
                _logger.info("Procesando respuesta de TechByThree")
                # TechByThree devuelve: {"Codigo": 0, "Mensaje": "", "Xml": "...", "CodigoQr": "..."}
                if json_response.get('Codigo') != 0:
                    error_msg = json_response.get('Mensaje', 'Error desconocido en timbrado')
                    _logger.error(f"Error TechByThree - Codigo: {json_response.get('Codigo')}, Mensaje: {error_msg}")
                    raise UserError(_('Error al timbrar: %s') % error_msg)
                
                # XML viene como string, no base64
                xml_content = json_response.get('Xml')
                if xml_content:
                    _logger.info("Procesando XML timbrado de TechByThree...")
                    # Convertir string XML a bytes para _set_data_from_xml
                    p._set_data_from_xml(xml_content.encode('utf-8'))
                    
                    # Crear attachment con el XML timbrado
                    xml_file_name = p.name.replace('.', '').replace('/', '_') + '.xml'
                    _logger.info(f"Creando attachment con nombre: {xml_file_name}")
                    
                    # Codificar XML a base64 para almacenar en datas
                    xml_base64_storage = base64.b64encode(xml_content.encode('utf-8')).decode('utf-8')
                    
                    attach = p.env['ir.attachment'].sudo().create({
                        'name': xml_file_name,
                        'datas': xml_base64_storage,
                        'res_model': p._name,
                        'res_id': p.id,
                        'type': 'binary',
                        'mimetype': 'application/xml',
                        'description': _('Factura CFDI del documento %s.') % p.name,
                    })
                    _logger.info(f"Attachment creado con ID: {attach.id}")
                    
                    if p.move_id:
                        cfdi_format = p.env.ref('cdfi_invoice.edi_cfdi_4_0')
                        edi_doc = p.env['account.edi.document'].sudo().create({
                            'edi_format_id': cfdi_format.id,
                            'state': 'sent',
                            'move_id': p.move_id.id,
                            'attachment_id': attach.id,
                        })
                    
                    estado_pago = 'pago_correcto'
                else:
                    _logger.error("TechByThree no devolvió XML")
                    raise UserError(_('Error: No se recibió XML del PAC'))
            else:
                # Procesamiento para otros proveedores (servidor, servidor2)
                estado_pago = json_response.get('estado_pago')
                _logger.info(f"Estado pago recibido: {estado_pago}")
                _logger.info(f"Tiene pago_xml: {bool(json_response.get('pago_xml'))}")
                _logger.info(f"Keys en json_response: {list(json_response.keys())}")
                
                if estado_pago == 'problemas_pago':
                    _logger.error(f"Problema en pago: {json_response.get('problemas_message')}")
                    raise UserError(_(json_response['problemas_message']))
                # Receive and stroe XML 
                if json_response.get('pago_xml'):
                    _logger.info("Procesando pago_xml recibido...")
                    p._set_data_from_xml(base64.b64decode(json_response['pago_xml']))

                    p._set_data_from_xml(base64.b64decode(json_response['pago_xml']))

                    xml_file_name = p.name.replace('.', '').replace('/', '_') + '.xml'
                    _logger.info(f"Creando attachment con nombre: {xml_file_name}")
                    attach = p.env['ir.attachment'].sudo().create(
                        {
                            'name': xml_file_name,
                            'datas': json_response['pago_xml'],
                         # 'datas_fname': xml_file_name,
                            'res_model': p._name,
                            'res_id': p.id,
                            'type': 'binary',
                            'mimetype': 'application/xml',
                            'description': _('Factura CFDI del documento %s.') % p.name,
                        })
                    _logger.info(f"Attachment creado con ID: {attach.id}")
                    if p.move_id:
                       cfdi_format = p.env.ref('cdfi_invoice.edi_cfdi_4_0')
                       edi_doc = p.env['account.edi.document'].sudo().create({
                           'edi_format_id': cfdi_format.id,
                           'state': 'sent',
                           'move_id': p.move_id.id,
                           'attachment_id': attach.id,
                       })
            
            _logger.info(f"Escribiendo estado_pago: {estado_pago}, xml_payment_link: {xml_file_link}")
            p.write({'estado_pago': estado_pago,
                     'xml_payment_link': xml_file_link})
            _logger.info("Publicando mensaje 'CFDI emitido'")
            p.message_post(body="CFDI emitido")
            _logger.info(f"=== FIN complete_payment exitoso para pago {p.name} ===")

    def _set_data_from_xml(self, xml_payment):
        if not xml_payment:
            return None
        NSMAP = {
            'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
            'cfdi': 'http://www.sat.gob.mx/cfd/4',
            'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital',
            'pago20': 'http://www.sat.gob.mx/Pagos20',
        }
        xml_data = etree.fromstring(xml_payment)
        Complemento = xml_data.find('cfdi:Complemento', NSMAP)
        TimbreFiscalDigital = Complemento.find('tfd:TimbreFiscalDigital', NSMAP)

        self.numero_cetificado = xml_data.attrib['NoCertificado']
        self.fecha_emision = xml_data.attrib['Fecha']
        self.cetificaso_sat = TimbreFiscalDigital.attrib['NoCertificadoSAT']
        self.fecha_certificacion = TimbreFiscalDigital.attrib['FechaTimbrado']
        self.selo_digital_cdfi = TimbreFiscalDigital.attrib['SelloCFD']
        self.selo_sat = TimbreFiscalDigital.attrib['SelloSAT']
        self.folio_fiscal = TimbreFiscalDigital.attrib['UUID']
        #self.folio = xml_data.attrib['Folio']
        version = TimbreFiscalDigital.attrib['Version']
        self.cadena_origenal = '||%s|%s|%s|%s|%s||' % (version, self.folio_fiscal, self.fecha_certificacion,
                                                       self.selo_digital_cdfi, self.cetificaso_sat)

        options = {'width': 275 * mm, 'height': 275 * mm}
        qr_value = 'https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?&id=%s&re=%s&rr=%s&tt=%s.%s&fe=%s' % (
        self.folio_fiscal,
        self.company_id.vat,
        self.partner_id.vat,
        '0000000000',
        '000000',
        self.selo_digital_cdfi[-8:],
        )
        self.qr_value = qr_value
        ret_val = createBarcodeDrawing('QR', value=qr_value, **options)
        self.qrcode_image = base64.encodebytes(ret_val.asString('jpg'))

    def send_payment(self):
        self.ensure_one()
        _logger.info('attach00')
        attachments = []
        _logger.info('attach01')
        domain = [
            ('res_id', '=', self.id),
            ('res_model', '=', self._name),
            ('name', '=', self.name.replace('.', '').replace('/', '_') + '.xml')]
        xml_file = self.env['ir.attachment'].search(domain, limit=1)
        if xml_file:
            _logger.info('attach02')
            _logger.info('pay_mail08')
            attachments.append((self.name.replace('.', '').replace('/', '_') + '.xml', xml_file.datas))

        _logger.info('send_mail01')
        template = self.env.ref('cdfi_invoice.email_template_payment', False)
        _logger.info('send_mail02')
        compose_form = self.env.ref('mail.email_compose_message_wizard_form', False)
        _logger.info('send_mail03')
        ctx = dict()
        ctx.update({
            'default_model': 'account.payment',
            'default_res_ids': [self.id],
            'default_use_template': bool(template),
            'default_template_id': template.id,
            'default_composition_mode': 'comment',
            #        'default_attachment_ids': attachments,
        })
        _logger.info('send_mail04')
        return {
            'name': _('Compose Email'),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(compose_form.id, 'form')],
            'view_id': compose_form.id,
            'target': 'new',
            'context': ctx,

        }

    def action_cfdi_cancel(self):
        for p in self:
            # if invoice.factura_cfdi:
            if p.estado_pago == 'factura_cancelada':
                pass
                # raise UserError(_('La factura ya fue cancelada, no puede volver a cancelarse.'))
            if not p.company_id.archivo_cer:
                raise UserError(_('Falta la ruta del archivo .cer'))
            if not p.company_id.archivo_key:
                raise UserError(_('Falta la ruta del archivo .key'))
            archivo_cer = p.company_id.archivo_cer.decode("utf-8")
            archivo_key = p.company_id.archivo_key.decode("utf-8")

            domain = [
                ('res_id', '=', p.id),
                ('res_model', '=', p._name),
                ('name', '=', p.name.replace('.', '').replace('/', '_') + '.xml')]
            xml_files = p.env['ir.attachment'].search(domain)
            if not xml_files:
                raise UserError(_('No se encontró el archivo XML para enviar a cancelar.'))
            xml_file = xml_files[0]
            values = {
                'rfc': p.company_id.vat,
                'api_key': p.company_id.proveedor_timbrado,
                'uuid': p.folio_fiscal,
                'folio': str(re.sub('[^0-9]','', p.name)),
                'serie_factura': str(re.sub(r'[0-9]+', '', p.name)).replace('/', '').replace('.', ''),
                'modo_prueba': p.company_id.modo_prueba,
                'certificados': {
                    'archivo_cer': archivo_cer,
                    'archivo_key': archivo_key,
                    'contrasena': p.company_id.contrasena,
                },
                'xml': xml_file.datas.decode("utf-8"),
                'motivo': p.env.context.get('motivo_cancelacion', '02'),
                'foliosustitucion': p.env.context.get('foliosustitucion', ''),
            }
            if p.company_id.proveedor_timbrado == 'servidor':
                url = '%s' % ('https://facturacion.itadmin.com.mx/api/refund')
            elif p.company_id.proveedor_timbrado == 'servidor2':
                url = '%s' % ('https://facturacion2.itadmin.com.mx/api/refund')
            elif p.company_id.proveedor_timbrado == 'techbythree':
                base_url = p.company_id.techbythree_url_base or 'https://dev.techbythree.com/api'
                if base_url.endswith('/api'):
                    base_url = base_url[:-4]
                base_url = base_url.rstrip('/')
                # TechByThree usa DELETE con UUID en la URL según documentación
                url = '%s/api/v1/facturacion/cancelar/%s' % (base_url, p.folio_fiscal)
                # TechByThree JSON API usa autenticación Bearer
                headers = {
                    'Authorization': 'Bearer %s' % p.company_id.techbythree_password,
                    'X-CLIENT-ID': p.company_id.techbythree_user,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }
                # Payload para cancelación con motivo y folio sustitución
                payload = {
                    'motivo': p.env.context.get('motivo_cancelacion', '02'),
                    'foliosustitucion': p.env.context.get('foliosustitucion', '')
                }
            else:
                raise UserError(_('Error, falta seleccionar el servidor de timbrado en la configuración de la compañía.'))

            if p.company_id.proveedor_timbrado == 'techbythree':
                # TechByThree usa DELETE
                response = requests.delete(url, json=payload, headers=headers)
                
                # Validar respuesta de TechByThree
                if response.status_code not in [200, 201, 204]:
                    raise UserError(_(f"Error del servidor PAC. Código HTTP: {response.status_code}. Respuesta: {response.text[:500]}"))
                
                # Para DELETE puede devolver 204 No Content (cancelación exitosa sin body)
                if response.status_code == 204 or not response.text or response.text.strip() == "":
                    p.write({'estado_pago': 'factura_cancelada'})
                    p.message_post(body="CFDI Cancelado exitosamente")
                    return
                
                try:
                    json_response = response.json()
                except (ValueError, requests.exceptions.JSONDecodeError):
                    raise UserError(_(f"Respuesta inválida del servidor PAC: {response.text[:500]}"))
                
                # Manejar respuesta de TechByThree
                if json_response.get('status') == 'success' or json_response.get('data'):
                    p.write({'estado_pago': 'factura_cancelada'})
                    p.message_post(body="CFDI Cancelado exitosamente")
                elif json_response.get('status') == 'error':
                    raise UserError(_(json_response.get('message', 'Error desconocido al cancelar')))
                else:
                    p.write({'estado_pago': 'factura_cancelada'})
                    p.message_post(body="CFDI Cancelado")
            else:
                # Otros proveedores usan POST
                response = requests.post(url,
                                         auth=None, data=json.dumps(values),
                                         headers={"Content-type": "application/json"})

                json_response = response.json()

                if json_response['estado_factura'] == 'problemas_factura':
                    raise UserError(_(json_response['problemas_message']))
                elif json_response.get('factura_xml', False):
                    file_name = 'CANCEL_' + p.name.replace('.', '').replace('/', '_') + '.xml'
                    p.env['ir.attachment'].sudo().create({
                        'name': file_name,
                        'datas': json_response['factura_xml'],
                        # 'datas_fname': file_name,
                        'res_model': p._name,
                        'res_id': p.id,
                        'type': 'binary'
                    })
                p.write({'estado_pago': json_response['estado_factura']})
                p.message_post(body="CFDI Cancelado")

    def truncate(self, number, decimals=0):
        """
        Returns a value truncated to a specific number of decimal places.
        """
        if not isinstance(decimals, int):
            raise TypeError("decimal places must be an integer.")
        elif decimals < 0:
            raise ValueError("decimal places has to be 0 or more.")
        elif decimals == 0:
            return math.trunc(number)

        factor = 10.0 ** decimals
        return math.trunc(number * factor) / factor

    def get_name(self):
        for payment in self:
            return payment.name.replace('.', '').replace('/', '_')


class MailComposeMessage(models.TransientModel):
    _inherit = 'mail.compose.message'

    def _compute_attachment_ids(self):
        res = super(MailComposeMessage, self)._compute_attachment_ids()
        for rec in self:
            if self.model == 'account.payment':
                attachment_ids=[]
                template_id = self.env.ref('cdfi_invoice.email_template_payment')
                if self.template_id.id == template_id.id:
                    res_ids = ast.literal_eval(self.res_ids)
                    for res_id in res_ids:
                        payment = self.env[self.model].browse(res_id)
                        domain = [
                            ('res_id', '=', payment.id),
                            ('res_model', '=', payment._name),
                            ('name', '=', payment.name.replace('.', '').replace('/', '_') + '.xml')]
                        xml_file = self.env['ir.attachment'].search(domain, limit=1)
                        if xml_file:
                            attachment_ids.extend(rec.attachment_ids.ids)
                            attachment_ids.append(xml_file.id)
                    if attachment_ids:
                        rec.attachment_ids = [(6, 0, attachment_ids)]
        return res


class AccountPaymentMail(models.Model):
    _name = "account.payment.mail"
    _inherit = ['mail.thread']
    _description = "Payment Mail"

    payment_id = fields.Many2one('account.payment', string='Payment')
    name = fields.Char(related='payment_id.name')
    xml_payment_link = fields.Char(related='payment_id.xml_payment_link')
    partner_id = fields.Many2one(related='payment_id.partner_id')
    company_id = fields.Many2one(related='payment_id.company_id')


class AccountPaymentTerm(models.Model):
    "Terminos de pago"
    _inherit = "account.payment.term"

    methodo_pago = fields.Selection(
        selection=[('PUE', 'Pago en una sola exhibición'),
                   ('PPD', 'Pago en parcialidades o diferido'), ],
        string='Método de pago',
    )
    forma_pago_id = fields.Many2one('catalogo.forma.pago', string='Forma de pago')
    company_cfdi = fields.Boolean(string='Compania CFDI', compute='_get_company')

    @api.depends('company_id')
    def _get_company(self):
        for record in self:
            if record.company_id:
                record.company_cfdi = record.company_id.company_cfdi
            else:
                record.company_cfdi = True


class FacturasPago(models.Model):
    _name = "facturas.pago"
    _description = 'Facturas ligadas a pago'

    doc_id = fields.Many2one('account.payment', 'Pago ligado')
    facturas_id = fields.Many2one('account.move', string='Factura')
    parcialidad = fields.Integer("Parcialidad")
    imp_saldo_ant = fields.Float("ImpSaldoAnt")
    imp_pagado = fields.Float("ImpPagado")
    imp_saldo_insoluto = fields.Float("ImpSaldoInsoluto", compute='_compute_insoluto')
    equivalenciadr = fields.Float("EquivalenciaDR", digits=(12, 10), default=1)

    @api.depends('imp_saldo_ant', 'imp_pagado')
    def _compute_insoluto(self):
        for rec in self:
            rec.imp_saldo_insoluto = rec.imp_saldo_ant - rec.imp_pagado

    @api.onchange('facturas_id')
    def _compute_saldo_ant(self):
        for rec in self:
            if rec.facturas_id:
                rec.imp_saldo_ant = rec.facturas_id.amount_total_in_currency_signed
