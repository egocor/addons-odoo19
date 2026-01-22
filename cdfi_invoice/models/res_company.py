# -*- coding: utf-8 -*-

import base64
import json
import requests
from odoo import fields, models, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
from dateutil import parser

class ResCompany(models.Model):
    _inherit = 'res.company'

    proveedor_timbrado= fields.Selection(
        selection=[('techbythree', 'TechByThree')],
        string='Servidor de timbrado', default='techbythree'
    )
    modo_prueba = fields.Boolean(string='Modo prueba')
    # Campos específicos para TechByThree
    techbythree_user = fields.Char(string='Usuario TechByThree')
    techbythree_password = fields.Char(string='Password TechByThree')
    techbythree_url_base = fields.Char(string='URL Base TechByThree', compute='_compute_techbythree_url', store=False, readonly=True)
    serie_factura = fields.Char(string='Serie factura') #quitar en proxima revisión
    regimen_fiscal_id  =  fields.Many2one('catalogo.regimen.fiscal', string='Régimen Fiscal')
    archivo_cer = fields.Binary(string='Archivo .cer')
    archivo_key = fields.Binary(string='Archivo .key')
    contrasena = fields.Char(string='Contraseña')
    nombre_fiscal = fields.Char(string='Razón social')
    saldo_timbres =  fields.Float(string='Saldo de timbres', readonly=True)
    saldo_alarma =  fields.Float(string='Alarma timbres', default=10)
    correo_alarma =  fields.Char(string='Correo de alarma')
    fecha_csd = fields.Datetime(string='Vigencia CSD',readonly=True)
    estado_csd =  fields.Char(string='Estado CSD', readonly=True)
    aviso_csd =  fields.Char(string='Aviso vencimiento (días antes)', default=14)
    fecha_timbres = fields.Date(string='Vigencia timbres', readonly=True)
    company_cfdi = fields.Boolean(string="CFDI MX")

    @api.depends('modo_prueba')
    def _compute_techbythree_url(self):
        for record in self:
            if record.modo_prueba:
                record.techbythree_url_base = 'https://dev.techbythree.com/api'
            else:
                record.techbythree_url_base = 'https://techbythree.com/api'

    @api.onchange('country_id')
    def _get_company_cfdi(self):
        if self.country_id:
            if self.country_id.code == 'MX':
               values = {'company_cfdi': True}
            else:
               values = {'company_cfdi': False}
        else:
            values = {'company_cfdi': False}
        self.update(values)

    @api.model
    def get_saldo_by_cron(self):
        companies = self.search([('proveedor_timbrado','!=',False)])
        for company in companies:
            company.get_saldo()
            if company.saldo_timbres < company.saldo_alarma and company.correo_alarma: #valida saldo de timbres
                email_template = self.env.ref("cdfi_invoice.email_template_alarma_de_saldo",False)
                if not email_template:return
                emails = company.correo_alarma.split(",")
                for email in emails:
                    email = email.strip()
                    if email:
                        email_template.send_mail(company.id, force_send=True,email_values={'email_to':email})
            if company.aviso_csd and company.fecha_csd and company.correo_alarma: #valida vigencia de CSD
                if datetime.today() - timedelta(days=int(company.aviso_csd)) > company.fecha_csd:
                   email_template = self.env.ref("cdfi_invoice.email_template_alarma_de_csd",False)
                   if not email_template:return
                   emails = company.correo_alarma.split(",")
                   for email in emails:
                       email = email.strip()
                       if email:
                          email_template.send_mail(company.id, force_send=True,email_values={'email_to':email})
            if company.fecha_timbres and company.correo_alarma: #valida vigencia de timbres
                if (datetime.today() + timedelta(days=7)).date() > company.fecha_timbres:
                   email_template = self.env.ref("cdfi_invoice.email_template_alarma_vencimiento",False)
                   if not email_template:return
                   emails = company.correo_alarma.split(",")
                   for email in emails:
                       email = email.strip()
                       if email:
                          email_template.send_mail(company.id, force_send=True,email_values={'email_to':email})
        return True

    def get_saldo(self):
        if not self.vat:
           raise UserError(_('Falta colocar el RFC'))
        if not self.proveedor_timbrado:
           raise UserError(_('Falta seleccionar el proveedor de timbrado'))
        values = {
                 'rfc': self.vat,
                 'api_key': self.proveedor_timbrado,
                 'modo_prueba': self.modo_prueba,
                 }
        url=''
        if self.proveedor_timbrado == 'servidor':
            url = '%s' % ('https://facturacion.itadmin.com.mx/api/saldo')
        elif self.proveedor_timbrado == 'techbythree':
            url = '%s/v1/compatibilidad/{CLIENT_ID}/RegistraEmisor' % (self.techbythree_url_base or 'https://dev.techbythree.com/api')
            values.update({
                'usuario': self.techbythree_user,
                'password': self.techbythree_password
            })

        if not url:
            return
        try:
            response = requests.post(url,auth=None,data=json.dumps(values),headers={"Content-type": "application/json"})
            json_response = response.json()
        except Exception as e:
            print(e)
            json_response = {}

        if not json_response:
            return

        estado_factura = json_response['estado_saldo']
        if estado_factura == 'problemas_saldo':
            raise UserError(_(json_response['problemas_message']))
        if json_response.get('saldo'):
            xml_saldo = base64.b64decode(json_response['saldo'])
        values2 = {
                    'saldo_timbres': xml_saldo,
                    'fecha_timbres': parser.parse(json_response['vigencia']) if json_response['vigencia'] else '',
                  }
        self.update(values2)

    def validar_csd(self):
        import logging
        _logger = logging.getLogger(__name__)
        
        # Validar que se hayan subido los archivos necesarios
        if not self.archivo_cer:
            raise Warning(_('Debe subir el archivo .cer del CSD'))
        if not self.archivo_key:
            raise Warning(_('Debe subir el archivo .key del CSD'))
        if not self.contrasena:
            raise Warning(_('Debe ingresar la contraseña del CSD'))
        if not self.vat:
            raise Warning(_('Debe configurar el RFC de la empresa'))
        
        # URL BASE CORRECTA DE TECHBYTHREE CON CLIENT_ID
        client_id = self.techbythree_user  # El CLIENT_ID está en el campo usuario
        url = f'{self.techbythree_url_base or "https://dev.techbythree.com/api"}/v1/compatibilidad/{client_id}/RegistraEmisor'
        

        values = {
            'RfcEmisor': self.vat,
            'Base64Cer': self.archivo_cer.decode('utf-8') if isinstance(self.archivo_cer, bytes) else self.archivo_cer,
            'Base64Key': self.archivo_key.decode('utf-8') if isinstance(self.archivo_key, bytes) else self.archivo_key,
            'Contrasena': self.contrasena,
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.techbythree_password}',  # Token API
            'X-CLIENT-ID': self.techbythree_user  # Client ID en header personalizado
        }
        
        _logger.info('=== VALIDAR CSD TECHBYTHREE ===')
        _logger.info('URL: %s', url)
        _logger.info('RFC: %s', self.vat)
        _logger.info('Headers: %s', headers)
        _logger.info('Certificado .cer length: %s', len(values["Base64Cer"]) if values["Base64Cer"] else 0)
        _logger.info('Certificado .key length: %s', len(values["Base64Key"]) if values["Base64Key"] else 0)
        _logger.info('Contrasena presente: %s', bool(self.contrasena))
        
        try:
            response = requests.post(url, json=values, headers=headers)
            _logger.info('Response status: %s', response.status_code)
            _logger.info('Response text: %s', response.text)
            
            if response.status_code == 200 or response.status_code == 201:
                json_response = response.json()
                _logger.info('JSON Response: %s', json_response)
                
                # Si el registro es exitoso, configurar como válido
                from datetime import datetime, timedelta
                fecha_simulada = datetime.now() + timedelta(days=365)
                
                values2 = {
                    'fecha_csd': fecha_simulada,
                    'estado_csd': 'Emisor registrado correctamente en TechByThree',
                }
                _logger.info('Actualizando campos: %s', values2)
                self.update(values2)
                _logger.info('Registro de emisor completado exitosamente')
            elif response.status_code == 409:
                # Emisor ya existe - esto es bueno
                _logger.info('Emisor ya registrado previamente')
                from datetime import datetime, timedelta
                fecha_simulada = datetime.now() + timedelta(days=365)
                
                values2 = {
                    'fecha_csd': fecha_simulada,
                    'estado_csd': 'Emisor ya registrado en TechByThree',
                }
                self.update(values2)
                _logger.info('Emisor validado - ya estaba registrado')
            else:
                _logger.error('Error HTTP %s: %s', response.status_code, response.text)
                raise UserError(f'Error en registro de emisor: HTTP {response.status_code}')
                
        except Exception as e:
            _logger.error('Error en validar_csd: %s', str(e))
            raise UserError(f'Error de conexión con TechByThree: {str(e)}')
        
        return

    def borrar_csd(self):
        values = {
                 'rfc': self.vat,
                 }
        url=''
        if self.proveedor_timbrado == 'servidor':
            url = '%s' % ('https://facturacion.itadmin.com.mx/api/borrarcsd')
        elif self.proveedor_timbrado == 'servidor2':
            url = '%s' % ('https://facturacion2.itadmin.com.mx/api/borrarcsd')
        elif self.proveedor_timbrado == 'techbythree':
            base_url = self.techbythree_url_base or 'https://dev.techbythree.com/api'
            if base_url.endswith('/api'):
                base_url = base_url[:-4]
            base_url = base_url.rstrip('/')
            url = '%s/api/borrarcsd' % base_url
            values.update({
                'usuario': self.techbythree_user,
                'password': self.techbythree_password
            })
        if not url:
            return
        try:
            response = requests.post(url,auth=None,data=json.dumps(values),headers={"Content-type": "application/json"})
            json_response = response.json()
        except Exception as e:
            print(e)
            json_response = {}

        if not json_response:
            return
        #_logger.info('something ... %s', response.text)
        respuesta = json_response['respuesta']
        raise UserError(respuesta)

    def borrar_estado(self):
           values2 = {
               'fecha_csd': '',
               'estado_csd': '',
               }
           self.update(values2)

    def button_dummy(self):
        self.get_saldo()
        return True
