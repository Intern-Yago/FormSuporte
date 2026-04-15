import logging
import re
from django.conf import settings
from clientes.models import Cliente, ClienteEndereco, ShopifySyncConfig
from clientes.integrations.shopify_client import ShopifyClient

logger = logging.getLogger(__name__)

class ShopifySyncService:
    def __init__(self):
        self.client = ShopifyClient(
            settings.SHOPIFY_STORE_URL, 
            settings.SHOPIFY_ACCESS_TOKEN
        )
        self.config, _ = ShopifySyncConfig.objects.get_or_create(id=1)

    def _extract_digits(self, value):
        return "".join(ch for ch in str(value or "") if ch.isdigit())

    def _extract_document(self, text):
        """
        Tenta extrair CPF ou CNPJ de um texto (geralmente notas do Shopify).
        """
        if not text:
            return None, None
            
        # Procura por sequências de 11 ou 14 dígitos (com ou sem pontuação)
        digits = self._extract_digits(text)
        
        # Regex para CPF (11) e CNPJ (14)
        cpf_match = re.search(r'\d{3}\.?\d{3}\.?\d{3}-?\d{2}', text)
        cnpj_match = re.search(r'\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}', text)
        
        if cnpj_match:
            return None, self._extract_digits(cnpj_match.group())
        if cpf_match:
            return self._extract_digits(cpf_match.group()), None
            
        # Se não achou com regex bonitinho, tenta por tamanho nos dígitos puros
        if len(digits) == 14:
            return None, digits
        if len(digits) == 11 and not digits.startswith('0'):
            return digits, None
            
        return None, None

    def sync_all_customers(self):
        """
        Puxa clientes do Shopify salvando o progresso para permitir retomada.
        """
        has_next = True
        # Se houver um cursor salvo, começa dele. Se não, começa do início (None).
        cursor = self.config.last_cursor
        count = 0

        logger.info(f"[SHOPIFY] Iniciando sincronização. Cursor atual: {cursor or 'Início'}")

        while has_next:
            try:
                result = self.client.list_customers(cursor=cursor)
                customers = result.get("customers", [])
                
                for cust_data in customers:
                    self.update_or_create_cliente(cust_data)
                    count += 1

                has_next = result.get("has_next_page", False)
                cursor = result.get("end_cursor")

                # Salva onde paramos após cada lote
                if has_next:
                    self.config.last_cursor = cursor
                    self.config.save()
                    logger.info(f"[SHOPIFY] Lote processado. {count} clientes até agora. Novo cursor salvo.")
                else:
                    # Chegou no fim: limpa o cursor para a próxima rodada começar do 0
                    self.config.last_cursor = None
                    self.config.save()
                    logger.info(f"[SHOPIFY] Sincronização concluída. Total: {count} clientes. Cursor resetado.")
                    break

            except Exception as e:
                logger.error(f"[SHOPIFY] Erro no lote (Cursor: {cursor}): {e}")
                # Não limpa o cursor em caso de erro, para poder tentar novamente do mesmo ponto
                raise e

        return count

    def update_or_create_cliente(self, cust_data):
        """
        Cria ou atualiza um cliente individual com base nos dados do Shopify.
        """
        email = cust_data.get("email")
        if not email:
            return None

        shopify_id = cust_data.get("id")
        nome = cust_data.get("display_name") or f"{cust_data.get('first_name', '')} {cust_data.get('last_name', '')}".strip()
        
        # 1. Telefone (Tenta principal, se não der, tenta dos endereços)
        telefone = cust_data.get("phone") or ""
        addresses = cust_data.get("addresses", [])
        if not telefone and addresses:
            for addr in addresses:
                if addr.get("phone"):
                    telefone = addr.get("phone")
                    break

        # 2. Documento (Tenta extrair das notas)
        note = cust_data.get("note") or ""
        cpf, cnpj = self._extract_document(note)

        # Tenta buscar por shopify_id primeiro, depois por email
        cliente = Cliente.objects.filter(shopify_customer_id=shopify_id).first()
        if not cliente:
            cliente = Cliente.objects.filter(email=email).first()

        if cliente:
            cliente.shopify_customer_id = shopify_id
            if not cliente.nome:
                cliente.nome = nome
            if (not cliente.telefone or len(cliente.telefone) < 5) and telefone:
                cliente.telefone = telefone
            
            # Só atualiza CPF/CNPJ se o cliente local estiver sem
            if not cliente.cpf and cpf:
                cliente.cpf = cpf
            if not cliente.cnpj and cnpj:
                cliente.cnpj = cnpj
                
            cliente.save()
        else:
            cliente = Cliente.objects.create(
                nome=nome,
                email=email,
                telefone=telefone,
                cpf=cpf,
                cnpj=cnpj,
                shopify_customer_id=shopify_id
            )

        # Sincroniza endereços se houver
        for addr in addresses:
            self.update_or_create_address(cliente, addr)

        return cliente

    def update_or_create_address(self, cliente, addr_data):
        """
        Sincroniza endereços do Shopify.
        """
        street = addr_data.get("address1") or ""
        city = addr_data.get("city") or ""
        uf = addr_data.get("provinceCode") or ""
        cep = addr_data.get("zip") or ""
        
        if not street:
            return

        exists = ClienteEndereco.objects.filter(
            cliente=cliente,
            endereco=street,
            cidade=city,
            cep=cep
        ).exists()

        if not exists:
            ClienteEndereco.objects.create(
                cliente=cliente,
                nome="Endereço Shopify",
                endereco=street,
                complemento=addr_data.get("address2") or "",
                cidade=city,
                uf=uf,
                cep=cep
            )
