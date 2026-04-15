from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
import xmlrpc.client
import base64

@dataclass
class OdooConfig:
    url: str
    db: str
    username: str
    password: str


class OdooClient:
    def __init__(self, cfg: OdooConfig):
        self.cfg = cfg

        base_url = cfg.url.replace("/jsonrpc", "").rstrip("/")

        self._common = xmlrpc.client.ServerProxy(f"{base_url}/xmlrpc/2/common")
        self._object = xmlrpc.client.ServerProxy(f"{base_url}/xmlrpc/2/object")
        self._uid: Optional[int] = None

    @property
    def uid(self) -> int:
        if self._uid is None:
            self._uid = self._common.authenticate(self.cfg.db, self.cfg.username, self.cfg.password, {})
            if not self._uid:
                raise RuntimeError("Falha ao autenticar no Odoo (credenciais/db/url).")
        return self._uid

    def partner_search(self, domain: list, *, limit: int = 1) -> list[int]:
        return self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "res.partner", "search",
            [domain],
            {"limit": limit}
        )

    def partner_create(self, vals: dict[str, Any]) -> int:
        return self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "res.partner", "create",
            [vals]
        )

    def partner_update(self, partner_id: int, vals: dict[str, Any]) -> bool:
        return bool(self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "res.partner", "write",
            [[int(partner_id)], vals]
        ))

    def partner_write(self, partner_id: int, vals: dict[str, Any]) -> bool:
        return bool(self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "res.partner", "write",
            [[partner_id], vals]
        ))

    def partner_read(self, partner_id: int, fields: list[str]) -> dict[str, Any]:
        rows = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "res.partner", "read",
            [[int(partner_id)], fields]
        )
        return rows[0] if rows else {}

    def search_model(self, model: str, domain: list, limit: int = 1) -> list[int]:
        return self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            model, "search",
            [domain],
            {"limit": limit}
        )

    def get_partner_category_id_by_name(self, nome: str) -> int | None:
        nome = (nome or "").strip()
        if not nome:
            return None

        ids = self.search_model(
            "res.partner.category",
            [("name", "=", nome)],
            limit=1
        )
        return ids[0] if ids else None

    def get_partner_category_ids(self, partner_id: int) -> list[int]:
        partner = self.partner_read(int(partner_id), ["category_id"])
        ids = partner.get("category_id", []) or []
        return [int(x) for x in ids]

    def add_category_to_partner(self, partner_id: int, category_id: int) -> bool:
        return self.partner_write(
            int(partner_id),
            {"category_id": [(4, int(category_id))]}
        )

    def ensure_partner_category_by_name(self, partner_id: int, nome_categoria: str) -> dict[str, Any]:
        category_id = self.get_partner_category_id_by_name(nome_categoria)
        atuais = self.get_partner_category_ids(partner_id)

        if not category_id:
            return {
                "category_id": None,
                "categoria_ok": False,
                "categoria_adicionada": False,
                "categorias_atuais": atuais,
            }

        categoria_ok = int(category_id) in atuais
        categoria_adicionada = False

        if not categoria_ok:
            self.add_category_to_partner(partner_id, category_id)
            categoria_adicionada = True
            atuais = self.get_partner_category_ids(partner_id)
            categoria_ok = int(category_id) in atuais

        return {
            "category_id": int(category_id),
            "categoria_ok": categoria_ok,
            "categoria_adicionada": categoria_adicionada,
            "categorias_atuais": atuais,
        }

    def find_partner_by_doc(
        self,
        *,
        tipo_faturamento: str | None = None,
        doc: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        name: str | None = None,
    ) -> Optional[int]:
        # 1) Busca por Documento (CPF/CNPJ) - Mais confiável
        if tipo_faturamento and doc:
            doc_digits = "".join(ch for ch in str(doc) if ch.isdigit())
            if len(doc_digits) == 11:
                doc_formatado = f"{doc_digits[:3]}.{doc_digits[3:6]}.{doc_digits[6:9]}-{doc_digits[9:]}"
            elif len(doc_digits) == 14:
                doc_formatado = f"{doc_digits[:2]}.{doc_digits[2:5]}.{doc_digits[5:8]}/{doc_digits[8:12]}-{doc_digits[12:]}"
            else:
                doc_formatado = doc

            domain = [(tipo_faturamento, "=", doc_formatado)]
            ids = self.partner_search(domain, limit=1)
            if ids:
                return ids[0]

            # Tenta busca por dígitos apenas
            if doc_digits != doc_formatado:
                domain = [(tipo_faturamento, "=", doc_digits)]
                ids = self.partner_search(domain, limit=1)
                if ids:
                    return ids[0]

        # 2) Busca por Email - Usar ilike para ser mais flexível (ignorar Fulano <...>)
        if email:
            email = email.strip().lower()
            # Tenta busca exata primeiro
            domain = [("email", "=", email)]
            ids = self.partner_search(domain, limit=1)
            if ids:
                return ids[0]
            
            # Tenta ilike para casos onde o email está formatado ou tem sufixos
            domain = [("email", "ilike", email)]
            ids = self.partner_search(domain, limit=1)
            if ids:
                return ids[0]

        # 3) Busca por Telefone (Phone ou Mobile)
        if phone:
            phone_digits = "".join(ch for ch in str(phone) if ch.isdigit())
            if len(phone_digits) >= 8:
                domain = ["|", ("phone", "ilike", phone_digits), ("mobile", "ilike", phone_digits)]
                ids = self.partner_search(domain, limit=1)
                if ids:
                    return ids[0]

        # 4) Busca por Nome (como último recurso antes de criar duplicata)
        if name and len(name.strip()) > 3:
            name_clean = name.strip()
            # Evita nomes genéricos como "Cliente" ou "Eaata"
            if name_clean.lower() not in ["cliente", "sem nome", "nao identificado", "eaata"]:
                domain = [("name", "ilike", name_clean)]
                ids = self.partner_search(domain, limit=1)
                if ids:
                    return ids[0]

        return None

    def buscar_ids_endereco(self, uf: str, cidade_nome: str) -> tuple[int | None, int | None, int | None]:
        country_id = None
        state_id = None
        city_id = None

        c_ids = self.search_model("res.country", [("code", "=", "BR")], limit=1)
        if not c_ids:
            c_ids = self.search_model("res.country", [("name", "ilike", "Brasil")], limit=1)
        if not c_ids:
            c_ids = self.search_model("res.country", [("name", "ilike", "Brazil")], limit=1)

        if c_ids:
            country_id = c_ids[0]

        if country_id and uf:
            s_ids = self.search_model(
                "res.country.state",
                [("code", "=", (uf or "").upper()), ("country_id", "=", country_id)],
                limit=1,
            )
            if not s_ids:
                s_ids = self.search_model(
                    "res.country.state",
                    [("code", "=", (uf or "").upper()), ("country_id.id", "=", country_id)],
                    limit=1,
                )
            if s_ids:
                state_id = s_ids[0]

        if state_id and cidade_nome:
            # tentativa 1
            m_ids = self.search_model(
                "l10n_br_ciel_it_account.res.municipio",
                [("name", "ilike", cidade_nome), ("state_id", "=", state_id)],
                limit=1,
            )

            # tentativa 2 - igual ao padrão que você validou no n8n
            if not m_ids:
                m_ids = self.search_model(
                    "l10n_br_ciel_it_account.res.municipio",
                    [("name", "ilike", cidade_nome), ("state_id.id", "=", state_id)],
                    limit=1,
                )

            if m_ids:
                city_id = m_ids[0]

        return country_id, state_id, city_id

    def buscar_produto(self, nome_busca: str) -> dict | None:
        import difflib
        import re

        palavras = nome_busca.split()
        if not palavras:
            return None

        busca_flexivel = "%" + "%".join(palavras) + "%"
        produtos_strict = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "product.product", "search_read",
            [[("name", "ilike", busca_flexivel), ("sale_ok", "=", True)]],
            {"fields": ["id", "name", "lst_price"], "limit": 1}
        )
        if produtos_strict:
            return produtos_strict[0]

        palavras_relevantes = [p for p in palavras if len(p) > 2]
        if not palavras_relevantes:
            return None

        domain_or = []
        for _ in range(len(palavras_relevantes) - 1):
            domain_or.append('|')

        for p in palavras_relevantes:
            domain_or.append(("name", "ilike", p))

        domain_final = domain_or + [("sale_ok", "=", True)]

        candidatos = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "product.product", "search_read",
            [domain_final],
            {"fields": ["id", "name", "lst_price"], "limit": 50}
        )

        if not candidatos:
            return None

        melhor_candidato = None
        maior_nota = 0.0

        busca_limpa = re.sub(r'[^a-zA-Z0-9\s]', ' ', nome_busca.upper())
        palavras_busca = set(busca_limpa.split())

        for candidato in candidatos:
            nome_odoo = candidato["name"].upper()
            odoo_limpo = re.sub(r'[^a-zA-Z0-9\s]', ' ', nome_odoo)
            palavras_odoo = set(odoo_limpo.split())

            acertos_exatos = len(palavras_busca.intersection(palavras_odoo))
            similaridade = difflib.SequenceMatcher(None, busca_limpa, odoo_limpo).ratio()
            nota_final = acertos_exatos + similaridade

            if nota_final > maior_nota:
                maior_nota = nota_final
                melhor_candidato = candidato

        if maior_nota >= 1.2:
            return melhor_candidato

        return None

    def buscar_vendedor_por_id(self, user_id: int) -> dict | None:
        if not user_id:
            return None

        usuarios = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "res.users", "read",
            [[int(user_id)], ["id", "name", "active", "login"]]
        )

        return usuarios[0] if usuarios else None


    def buscar_vendedor_por_email(self, email: str) -> dict | None:
        email = (email or "").strip().lower()
        if not email:
            return None

        usuarios = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "res.users", "search_read",
            [[
                ["active", "in", [True, False]],
                ["login", "=", email]
            ]],
            {"fields": ["id", "name", "active", "login"], "limit": 1}
        )

        if usuarios:
            return usuarios[0]

        usuarios = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "res.users", "search_read",
            [[
                ["active", "in", [True, False]],
                ["login", "ilike", email]
            ]],
            {"fields": ["id", "name", "active", "login"], "limit": 1}
        )

        return usuarios[0] if usuarios else None

    def buscar_vendedor(self, nome_busca: str) -> dict | None:
        """
        Busca o ID do vendedor na tabela res.users do Odoo através do nome.
        Inclui ativos e inativos.
        """
        nome_busca = (nome_busca or "").strip()
        if not nome_busca:
            return None

        domain = [
            ["active", "in", [True, False]],
            ["name", "ilike", nome_busca]
        ]

        usuarios = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "res.users", "search_read",
            [domain],
            {"fields": ["id", "name", "active", "login"], "limit": 1}
        )

        if usuarios:
            return usuarios[0]

        # fallback por login
        usuarios = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "res.users", "search_read",
            [[
                ["active", "in", [True, False]],
                ["login", "ilike", nome_busca]
            ]],
            {"fields": ["id", "name", "active", "login"], "limit": 1}
        )

        return usuarios[0] if usuarios else None

    def criar_vendedor(self, nome_usuario: str, email: str | None = None) -> dict:
        """
        Cria um usuário vendedor no Odoo em res.users.
        Prioriza email como login; se não houver, usa nome normalizado.
        Retorna um dict com id, name, login e active.
        """
        nome_usuario = (nome_usuario or "").strip()
        email = (email or "").strip().lower()

        if not nome_usuario:
            raise ValueError("Nome do vendedor vazio.")

        if email:
            login_base = email
        else:
            login_base = nome_usuario.lower().strip().replace(" ", ".")

        login = login_base
        idx = 1

        while True:
            existentes = self._object.execute_kw(
                self.cfg.db, self.uid, self.cfg.password,
                "res.users", "search_read",
                [[["login", "=", login]]],
                {"fields": ["id", "login"], "limit": 1}
            )
            if not existentes:
                break

            idx += 1
            if email:
                partes = email.split("@", 1)
                if len(partes) == 2:
                    login = f"{partes[0]}.{idx}@{partes[1]}"
                else:
                    login = f"{email}.{idx}"
            else:
                login = f"{login_base}.{idx}"

        user_id = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "res.users", "create",
            [{
                "name": nome_usuario,
                "login": login,
                "sel_groups_1_9_10": 10,
                "active": False,
            }]
        )

        usuario = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "res.users", "read",
            [[int(user_id)], ["id", "name", "login", "active"]]
        )

        return usuario[0] if usuario else {
            "id": int(user_id),
            "name": nome_usuario,
            "login": login,
            "active": False,
        }


    def buscar_ou_criar_vendedor(
        self,
        nome_busca: str,    
        *,
        email: str | None = None,
        odoo_user_id: int | None = None,
    ) -> dict:
        """
        Ordem de busca:
        1. odoo_user_id
        2. email/login
        3. nome
        4. cria se não encontrar
        """
        if odoo_user_id:
            vendedor = self.buscar_vendedor_por_id(odoo_user_id)
            if vendedor:
                vendedor["created"] = False
                vendedor["found_by"] = "id"
                return vendedor

        if email:
            vendedor = self.buscar_vendedor_por_email(email)
            if vendedor:
                vendedor["created"] = False
                vendedor["found_by"] = "email"
                return vendedor

        vendedor = self.buscar_vendedor(nome_busca)
        if vendedor:
            vendedor["created"] = False
            vendedor["found_by"] = "nome"
            return vendedor

        vendedor = self.criar_vendedor(nome_busca, email=email)
        vendedor["created"] = True
        vendedor["found_by"] = "created"
        return vendedor
    
    def criar_endereco_entrega_partner(
        self,
        *,
        parent_id: int,
        nome: str,
        endereco: str | None = None,
        numero: str | None = None,
        complemento: str | None = None,
        bairro: str | None = None,
        cidade_nome: str | None = None,
        uf: str | None = None,
        cep: str | None = None,
    ) -> int:
        """
        Cria um endereço de entrega (child contact) vinculado ao partner principal no Odoo.
        """
        country_id, state_id, municipio_id = self.buscar_ids_endereco(uf or "", cidade_nome or "")

        vals = {
            "parent_id": int(parent_id),
            "type": "delivery",
            "name": (nome or "Endereço de Entrega").strip(),
            "street": (endereco or "").strip() or False,
            "l10n_br_endereco_numero": (numero or "").strip() or False,
            "street2": (complemento or "").strip() or False,
            "l10n_br_endereco_bairro": (bairro or "").strip() or False,
            "zip": "".join(ch for ch in str(cep or "") if ch.isdigit()) or False,
            "is_company": False,
            "company_type": "person",
        }

        if country_id:
            vals["country_id"] = country_id
        if state_id:
            vals["state_id"] = state_id
        if municipio_id:
            vals["l10n_br_municipio_id"] = municipio_id

        endereco_id = self.partner_create(vals)

        vals_pos_create = {}
        if country_id:
            vals_pos_create["country_id"] = country_id
        if state_id:
            vals_pos_create["state_id"] = state_id
        if municipio_id:
            vals_pos_create["l10n_br_municipio_id"] = municipio_id

        if vals_pos_create:
            try:
                self.partner_write(endereco_id, vals_pos_create)
            except Exception:
                pass

        return int(endereco_id)
    
    def buscar_endereco_entrega_existente(
        self,
        *,
        parent_id: int,
        endereco: str | None = None,
        numero: str | None = None,
        bairro: str | None = None,
        cep: str | None = None,
    ) -> int | None:
        domain = [
            ("parent_id", "=", int(parent_id)),
            ("type", "=", "delivery"),
        ]

        if endereco:
            domain.append(("street", "ilike", endereco.strip()))
        if numero:
            domain.append(("l10n_br_endereco_numero", "=", numero.strip()))
        if bairro:
            domain.append(("l10n_br_endereco_bairro", "ilike", bairro.strip()))

        cep_digits = "".join(ch for ch in str(cep or "") if ch.isdigit())
        if cep_digits:
            domain.append(("zip", "=", cep_digits))

        ids = self.partner_search(domain, limit=1)
        return ids[0] if ids else None
    
    def criar_endereco_entrega(
        self,
        partner_id: int,
        *,
        name: str,
        street: str,
        numero: str,
        complemento: str,
        bairro: str,
        zip_code: str,
        city_id: int | None,
        state_id: int | None,
        country_id: int | None,
    ) -> int:

        vals = {
            "parent_id": partner_id,
            "type": "delivery",
            "name": name,

            "street": street or False,
            "l10n_br_endereco_numero": numero or False,
            "street2": complemento or False,
            "l10n_br_endereco_bairro": bairro or False,
            "zip": zip_code or False,
        }

        if country_id:
            vals["country_id"] = country_id

        if state_id:
            vals["state_id"] = state_id

        if city_id:
            vals["l10n_br_municipio_id"] = city_id

        return self.partner_create(vals)
    
    def buscar_contatos_filhos(self, partner_id: int) -> list[dict[str, Any]]:
        domain = [("parent_id", "=", int(partner_id))]
        fields = [
            "id", "name", "type", "street", "l10n_br_endereco_numero", 
            "street2", "l10n_br_endereco_bairro", "city", "l10n_br_municipio_id", "state_id", "zip"
        ]
        return self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "res.partner", "search_read",
            [domain],
            {"fields": fields}
        )

    def buscar_pedidos_venda_por_partner(self, partner_id: int, limit: int = 50) -> list[dict[str, Any]]:
        domain = [("partner_id", "=", int(partner_id))]
        fields = [
            "id", "name", "date_order", "amount_total", "state", 
            "note", "payment_term_id", "validity_date"
        ]
        
        orders = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "sale.order", "search_read",
            [domain],
            {"fields": fields, "limit": limit, "order": "date_order desc"}
        )
        return orders

    def sale_order_create(self, vals: dict[str, Any]) -> int:
        return self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "sale.order", "create",
            [vals]
        )

    def sale_order_read(self, order_id: int, fields: list[str]) -> dict[str, Any]:
        rows = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "sale.order", "read",
            [[int(order_id)], fields]
        )
        return rows[0] if rows else {}

    def sale_order_line_create(self, vals: dict[str, Any]) -> int:
        return self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "sale.order.line", "create",
            [vals]
        )
    
    def fields_get(self, model: str, fields: list[str]) -> dict:
        return self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            model, "fields_get",
            [fields],
            {"attributes": ["type", "string", "required", "selection"]}
        )
    
    def buscar_payment_provider(self, nome: str) -> dict | None:
        nome = (nome or "").strip()
        if not nome:
            return None

        rows = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "payment.provider", "search_read",
            [[("name", "=", nome)]],
            {"fields": ["id", "name"], "limit": 1}
        )

        if rows:
            return rows[0]

        rows = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "payment.provider", "search_read",
            [[("name", "ilike", nome)]],
            {"fields": ["id", "name"], "limit": 1}
        )

        return rows[0] if rows else None

    def sale_order_call_method(self, order_id: int, method_name: str):
        return self._object.execute_kw(
            self.cfg.db,
            self.uid,
            self.cfg.password,
            "sale.order",
            method_name,
            [[int(order_id)]],
        )
        
    def adicionar_nota_pedido(self, order_id: int, texto: str) -> bool:
        return bool(self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "sale.order", "write",
            [[int(order_id)], {"note": texto}]
        ))
    


    def anexar_arquivo_em_sale_order(self, sale_order_id: int, nome_arquivo: str, conteudo: bytes, mimetype: str | None = None) -> int:
        datas = base64.b64encode(conteudo).decode("utf-8")

        vals = {
            "name": nome_arquivo,
            "type": "binary",
            "datas": datas,
            "res_model": "sale.order",
            "res_id": int(sale_order_id),
        }

        if mimetype:
            vals["mimetype"] = mimetype

        attachment_id = self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "ir.attachment", "create",
            [vals]
        )
        return int(attachment_id)
    
    def postar_anexo_no_chatter(self, sale_order_id: int, attachment_id: int, body: str = "Documento enviado pelo painel"):
        return self._object.execute_kw(
            self.cfg.db,
            self.uid,
            self.cfg.password,
            "sale.order",
            "message_post",
            [[int(sale_order_id)]],
            {
                "body": body,
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_note",
                "attachment_ids": [int(attachment_id)],
            },
        )

    def sale_order_write(self, sale_order_id: int, vals: dict[str, Any]) -> bool:
        return bool(self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "sale.order", "write",
            [[int(sale_order_id)], vals]
        ))

    def adicionar_nota_interna_pedido(self, sale_order_id: int, texto: str) -> int:
        body = f"<pre>{texto}</pre>"

        return int(self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "sale.order", "message_post",
            [[int(sale_order_id)]],
            {
                "body": body,
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_note",
            }
        ))
    
    def get_model_id(self, model_name: str) -> int | None:
        ids = self._object.execute_kw(
            self.cfg.db,
            self.uid,
            self.cfg.password,
            "ir.model",
            "search",
            [[("model", "=", model_name)]],
            {"limit": 1},
        )
        return int(ids[0]) if ids else None


    def get_todo_activity_type_id(self) -> int | None:
        ids = self._object.execute_kw(
            self.cfg.db,
            self.uid,
            self.cfg.password,
            "mail.activity.type",
            "search",
            [[("category", "=", "default")]],
            {"limit": 1},
        )
        return int(ids[0]) if ids else None


    def agendar_atividade_pedido(
        self,
        sale_order_id: int,
        user_id: int,
        summary: str,
        note: str = "",
    ) -> int:
        model_id = self.get_model_id("sale.order")
        if not model_id:
            raise RuntimeError("Não foi possível localizar ir.model de sale.order no Odoo.")

        activity_type_id = self.get_todo_activity_type_id()
        if not activity_type_id:
            raise RuntimeError("Não foi possível localizar mail.activity.type no Odoo.")

        vals = {
            "res_model_id": int(model_id),
            "res_id": int(sale_order_id),
            "user_id": int(user_id),
            "activity_type_id": int(activity_type_id),
            "summary": summary,
            "note": note or "",
        }

        activity_id = self._object.execute_kw(
            self.cfg.db,
            self.uid,
            self.cfg.password,
            "mail.activity",
            "create",
            [vals],
        )
        return int(activity_id)
    

    def buscar_usuario_odoo(self, termo: str) -> dict | None:
        termo = (termo or "").strip()
        if not termo:
            return None

        domain = ["|", ("name", "ilike", termo), ("login", "ilike", termo)]

        ids = self._object.execute_kw(
            self.cfg.db,
            self.uid,
            self.cfg.password,
            "res.users",
            "search",
            [domain],
            {"limit": 1},
        )

        if not ids:
            return None

        data = self._object.execute_kw(
            self.cfg.db,
            self.uid,
            self.cfg.password,
            "res.users",
            "read",
            [ids, ["id", "name", "login"]],
        )

        return data[0] if data else None
    
    def sale_order_line_search(self, sale_order_id: int) -> list[int]:
        return self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "sale.order.line", "search",
            [[("order_id", "=", int(sale_order_id))]]
        )

    def sale_order_line_unlink(self, line_ids: list[int]) -> bool:
        if not line_ids:
            return True
        return bool(self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "sale.order.line", "unlink",
            [line_ids]
        ))

    def sale_order_replace_lines(self, sale_order_id: int, linhas: list[dict]) -> list[int]:
        antigas = self.sale_order_line_search(sale_order_id)
        if antigas:
            self.sale_order_line_unlink(antigas)

        novas = []
        for linha in linhas:
            vals = dict(linha)
            vals["order_id"] = int(sale_order_id)
            line_id = self.sale_order_line_create(vals)
            novas.append(int(line_id))
        return novas
    
    def sale_order_action_confirm(self, order_id: int) -> bool:
        return bool(self._object.execute_kw(
            self.cfg.db, self.uid, self.cfg.password,
            "sale.order", "action_confirm",
            [[int(order_id)]]
        ))