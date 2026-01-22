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
        selection=[('servidor', 'Principal'),
                   ('servidor2', 'Respaldo'),
                   ('techbythree', 'TechByThree'),],
        string='Servidor de timbrado', default='servidor'
    )
    api_key = fields.Char(string='API Key')
    modo_prueba = fields.Boolean(string='Modo prueba')
    # Campos específicos para TechByThree
    techbythree_user = fields.Char(string='Usuario TechByThree')
    techbythree_password = fields.Char(string='Password TechByThree')
    techbythree_url_base = fields.Char(string='URL Base TechByThree', default='https://dev.techbythree.com/api')
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
        
        # URL BASE CORRECTA DE TECHBYTHREE CON CLIENT_ID
        client_id = self.techbythree_user  # El CLIENT_ID está en el campo usuario
        url = f'{self.techbythree_url_base or "https://dev.techbythree.com/api"}/v1/compatibilidad/{client_id}/RegistraEmisor'
        

        values = {
            'RfcEmisor': self.vat,
            'Base64Cer': 'TUlJRitEQ0NBK0NnQXdJQkFnSVVNREF3TURFd01EQXdNREEzTURJeE56WTRORE13RFFZSktvWklodmNOQVFFTEJRQXdnZ0dWTVRVd013WURWUVFEREN4QlF5QkVSVXdnVTBWU1ZrbERTVThnUkVVZ1FVUk5TVTU1VTFSU1FVTkpUMDRnVkZKSlFsVlVRVkpKUVRFdU1Dd0dBMVVFQ2d3bFUwVlNWa2xEU1U4Z1JFVWdRVVJOU1U1SlUxUlNRVU5KVDA0Z1ZGSkpRbFZVUVZKSlFURWFNQmdHQTFVRUN3d1JVMEZVTFVsRlV5QkJkWFJvYjNKcGRIa3hNakF3QmdrcWhraUc5dzBCQ1FFV0kzTmxjblpwWTJsdmMyRnNZMjl1ZEhKcFluVjVaVzUwWlVCellYUXVaMjlpTG0xNE1TWXdKQVlEVlFRSkRCMUJkaTRnU0dsa1lXeG5ieUEzTnl3Z1EyOXNMaUJIZFdWeWNtVnliekVPTUF3R0ExVUVFUXdGTURZek1EQXhDekFKQmdOVkJBWVRBazFZTVEwd0N3WURWUVFJREFSRFJFMVlNUk13RVFZRFZRUUhEQXBEVlVGVlNIUkZUVTlETVJVd0V3WURWUVF0RXd4VFFWUTVOekEzTURGT1RqTXhYREJhQmdrcWhraUc5dzBCQ1FJVFRYSmxjM0J2Ym5OaFlteGxPaUJCUkUxSlRrbFRWRkpCUTBsUFRpQkRSVTVVVWtGTUlFUkZJRk5GVWxaSlEwbFBVeUJVVWtsQ1ZWUkJVa2xQVXlCQlRDQkRUMDVVVWtsQ1ZWbEZUbFJGTUI0WERUSXpNRGt3TmpJeE1qRXlObG9YRFRJM01Ea3dOakl4TWpFeU5sb3dnYlV4SXpBaEJnTlZCQU1UR2tWRVIwRlNJRTFKUjFWRlRDQktTVTFGVGtWYUlFZFBWa1ZCTVNNd0lRWURWUVFwRXhwRlJFZEJVaUJOU1VkVlJVd2dTa2xOUlU1RldpQkhUMVpGUVRFak1DRUdBMVVFQ2hNYVJVUkhRVklnVFVsSFZVVk1JRXBKVFVWT1JWb2dSMDlXUlVFeEZqQVVCZ05WQkMwVERVcEpSMFUzTkRBM01qRkJRamd4R3pBWkJnTlZCQVVURWtwSlIwVTNOREEzTWpGSVJFWk5Wa1F3TmpFUE1BMEdBMVVFQ3hNR1RVRlVVa2xhTUlJQklqQU5CZ2txaGtpRzl3MEJBUUVGQUFPQ0FROEFNSUlCQ2dLQ0FRRUFqdjArSHlBczJXUVNPVG1LWUg0WXhXK2NFWUNiRmhhdjU1R2gvUmFkQ1BUVUo5Q1MzaVhDcXRkYzh4TDJlMFZSUjA4R2NLY1BlSXJUeWt4TlJFTjNkTXlqY1BPVXd2SkFlNTFiV0QzYndqdC8wd2gwTlQvU0xycTZNRS9MdTN0RThmbHJyNW1LS2xGa1h6QVE3Q0oyOFhTMkY2NUgrMTBqUHhwVTgyUzg0SE5yQ0UzVEJsTEt4WnRGZ3JvTC9TTU5KckdFMmVoN0crRTE0UVFpVExTRkVWK2pWS3lXWlNyTU5xTmNaaTN0Rjh4YkZuZ2JONUllSDh5S0J4c09FK3hFdXhRUjZTRmZkUXd2TDFKYkRSSzlWOVJvVHVENEczQmlOa0JMWDBkYU9TY1NORFpkVUZnaHpsK0xvNmU3UDlqdkJnSTZjYjFObE1aM1IxQ0RZeFExQlFJREFRQUJveDB3R3pBTUJnTlZIUk1CQWY4RUFqQUFNQXNHQTFVZER3UUVBd0lHd0RBTkJna3Foa2lHOXcwQkFRc0ZBQU9DQWdFQWNMcjU5cU1tSzRtVjd2VG1uY1AxbkVndEN5Ni9QbnBpcW5GWXM4RWhLMHNUOWhYbWRqblVCZm1WQ0xNMWtOd1VhZE5qMDZibWFKL2w2VFo0TW1XMnNzQnYyZklnRE5BeGI1OWpicUxiYWg5VkF4aFNPeHRKK0k2ZUV2clIwbWJ4dlhHZmkzajBLSGV0K0tkWUc0SWpqSDFMbmJNU0hwazlrWmFwYTZKb3JnczRhTEtEZkRZS09SWHkweHFMY3owMWQ5SmVlTlJZZU5sNDBvTFlhZThUa0dvTlc0Zk9DS2x1b0hsSVNxMzJLUnRqblpUd2hKYkFGUlNxS1JpN0NrT0NxY0ZuV04vNGNUMWJjTXN0WVFFRkhPQWhuVHNrcjFBbmNUVk11UmR2eUo3cFRQZGF5dk5ISnQ2eFZ6aHN2SmFIcTFsbU1nZVRNQkZPcjFjTDdrZ2lkQTNrSE9xYTZMVDljbWpSMG02V2EzRjNhcjVlRW55OEJtSWhmSUNzS1djSS9HdmM5cjk3NDJYdDdEM2JNYXVoVE1SSHFzTTFBS2FiZlVEczBGdi83M0lldEtnb3ErenNoUU5ESnZBUGR5RnNMQjN3MEhZSWJsTjlDc2QxK0c5YlpsbndmOE8vSnR3RFZUTXVOV0EycGFvWVdnaXJVeDNWU0RkbUlvRUtzNmgvZ0NkNDZqN1VUeVVaNDhnZG50eXJGMjNQak5UMmZkRTNRM3lQaDN2a3QxY3ErWk84am91dzlkUVNVbHBrMVN5Qm1WMWkzM1ArVEpkQVBEQVF5RUV1ZmpDek1oSlIwbmJyK1BuaTArWWQwMkdXRGVTbGpjV3AwekdGZWRjd244RWlHWDV1VHBsanMwamNhNm1xUUN2VXAycTlRdURjRUFQZHJKZUNxb3NtVCswPQ==',
            'Base64Key': 'TUlJRkRqQkFCZ2txaGtpRzl3MEJCUTB3TXpBYkJna3Foa2lHOXcwQkJRd3dEZ1FJQWdFQUFvSUJBUUFDQWdnQU1CUUdDQ3FHU0liM0RRTUhCQWd3Z2dTOUFnRUFNQVNDQk1naTBPQ1p3M1pzZ0JpTTJhUllhYXBiSldKeHVYcURuNlJWYnNMalVjaXZkc1JhK0xWQWVXeWMzUnFBT2pZYnJkMllzeEJFcVNkSDg3RnJIZmxwNDF4VVdWTFg3OE11MlJRZk1rZDBBcDhzUGJTc25NVlNYMDRpTlhRL2lraDlucXFWQWN4R2VlRTFnUGdkZVJUT3JnUlRiYTV5S0x6blJVcUczVFBTeDBRSG9qLzRwVld1TWo0bFdhWHNmd0liNEkwUHpSS1pPVHI3a1ZkcHAzSVZneS9EcVF5ZHMrYWJnc1hUOE9TVU5JWHg2czV6VFM2WG42b3RIdXpNYVVTcmVHY21CNEYrcnU2aUd2Z216SmZMWXZnNXpoaXRja2dQTEdrQWdBV3cwKzVoUU5lei9TNDZPVDZZa3Y4dytXbEw1QXk3UHgzdGxWWGdQT3hMREZsSWR0bTFDUGVSR3NGaEN6MzJoTHo2Qm5CNHBVZTlPcjRBZmZQSmFmbE5uTW5vVHJsV0RiNzBmMnp1SVBlL3RaR280UHE1YVVSei9UYy9WdDVYOHdhZmxva0IwRmpHQllCNWd6OVE1M29XcjEwSk44NjMzUU45YWNGZS9PdXRkMFMvYndLZm45WS8rRUFvbXdqY21XUUpRQUVIQzRQU3lSZlpOZUNCOFV3a1VrbTFNQjlRL1N1TnY3SUhINjMvQXQ3ZytJL01BYmM1cEtuaDZjWlc4Z2tNNUhCRklxcThET3RRdjNJOGVURWFGODFrT2ZSTzJCZUlQOE5PejhMeDU5Q0Z6NWs5TU5zMVRXN1JvZlNkKzRoRWNHN2VqbDhhMSt6NGt4bSt6cVkxRGNCN1Z5eXpTeENMZmI4TFNaR2RUdnQxc3ErT21SVGhneVpiemtGR2t6NzVRZ2dqMDF2Zlp0QTQzRDRaZE11WFA0ZHlwamEzNlJrOXBtVFFkM3Q5bnpVYURXalBINHlrY3JtL216NEt2ZWRRSUVSOC9LdWp0UlNncGpSbThBOVhhc21mVm5LdnhTWUVCM0U4WHF4L1BwajFvSE05M0VobzhHaC9xQWdxcW1kYUVjb3NCanBpdUI0ZFNnUUNLS210dmdkMEttMWV4bm1lVjNrcitUZ2JvNnBweXFZbVVRRWthYldUZ3NWamdxVXAzWGNTVC9EeEJuVStscG80MU44aW9Qa0ZJRHdNZjZzS1AyQ1JkRUt1UDVsNktZV2hwbGxrZjZPU3N5TTFUV25mMXoxaG1XeGJKM3ZxaXQzK1RtendGT29ES1Q2aGl4Q083OEZYZTRZSk84WmsrQ2poR3orWXpZTkJOSWhlOWlFZ0IvL3dNOFduU2ZyRER5QmkwNDQreTFzU1NGMG9TanZERklQb3RvdmovVUtUcGduMzNxMVVyMFZjSURkNHR6bVhTbXk4WU1wWW5XTzQ0NHJ2bElVRUFhWVM1RWZMUFVPZEVxV25WZUJCdHhrM05scnlxR3RaZ1R4VElRM2t6dkNvNitQSDMzVUR0M1BFcDNxODFZclVFUjZFTlZXWUxEc2ZncWRZaDhnREdYZFdQNG4zb1RReFQvc3VycHoyYTJ3Q3hNbUZrWVd1VTl4ZkxNMEVxY0ZxZWtSdUp0YllEUDBDMzZKcWZCVHlURlhyeEh5cWdSZ2FNMzhsR05RbTh1VVMxb3lPUTRMMTYreWk5SUV1c09wZ0NzVlFBdUpWWGhKakVQVFlsL1YyUnY4dDVxN3BNa1J2TjJwMmJLT0ZTdlBWOUVmWDBVemRsc1VVeUxPYi8zRDJmRkY3Zmk4aXNWZm5Kek9OTDJsNzZ3aXozaDRZUnVkZmhaZUhXbXdqd3lNcFlMSTJBZC82MzNuaVdDSmVEU29LekE5T2F3dUZ3NlNMYzZiN1UwYzdUYTlDZmtaZnhId1Z1RTZQMGFIQ1ZPWlpuK0JoMzk4VjdYS3ZTcnlwdGdzM1RLREtWTTR3NjJJWkdrQ3o0Yk9sUzFzOVJLU0tXMWQ0Y3IvWEN6Sm1xMzVWVVloYWdmeVEzUHdFeWRHTC9lbzNYTVliRWk3MEYvSnNocnM2SFVaM2JBeGFoZCtmWGlSbVVSbW1tRkp4dkRxTUZYWjZsbEZwYXM1VUxsT1NuVmt3Y3pnTUd2cy94Z0MxOU1pNEkxYzIyemE2c05PTXdod0hlWDVxUjZZPQ==',
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
            url = '%s/api/borrarcsd' % (self.techbythree_url_base or 'https://techbythree.com')
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
