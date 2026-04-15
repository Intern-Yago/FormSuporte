import requests
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

class ShopifyClient:
    def __init__(self, store_url: str, access_token: str):
        """
        :param store_url: Ex: "minha-loja.myshopify.com"
        :param access_token: Admin API access token
        """
        self.store_url = store_url.strip().replace("https://", "").replace("http://", "").rstrip("/")
        self.access_token = access_token
        self.api_url = f"https://{self.store_url}/admin/api/2025-07/graphql.json"
        self.headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.access_token,
        }

    def _execute_query(self, query: str, variables: Optional[dict] = None) -> dict:
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = requests.post(self.api_url, json=payload, headers=self.headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            if "errors" in data:
                logger.error(f"Shopify GraphQL Errors: {data['errors']}")
            return data
        except Exception as e:
            logger.error(f"Error executing Shopify GraphQL query: {e}")
            return {"data": None, "errors": [str(e)]}

    def get_customer_data(self, email: str, cursor: Optional[str] = None) -> Optional[dict]:
        """
        Busca raio-x completo do cliente e suporte a paginação de pedidos.
        """
        query = """
        query getCustomer($query: String!, $cursor: String) {
          customers(first: 1, query: $query) {
            edges {
              node {
                id
                firstName
                lastName
                displayName
                email
                phone
                createdAt
                note
                tags
                verifiedEmail
                numberOfOrders
                amountSpent {
                  amount
                  currencyCode
                }
                emailMarketingConsent {
                  marketingState
                }
                addresses {
                  address1
                  address2
                  city
                  provinceCode
                  zip
                  country
                }
                orders(first: 10, after: $cursor, sortKey: CREATED_AT, reverse: true) {
                  pageInfo {
                    hasNextPage
                    endCursor
                  }
                  edges {
                    node {
                      id
                      name
                      createdAt
                      subtotalPriceSet {
                        presentmentMoney {
                          amount
                        }
                      }
                      totalDiscountsSet {
                        presentmentMoney {
                          amount
                        }
                      }
                      totalPriceSet {
                        presentmentMoney {
                          amount
                          currencyCode
                        }
                      }
                      discountApplications(first: 5) {
                        edges {
                          node {
                            ... on DiscountCodeApplication {
                              code
                            }
                            ... on ManualDiscountApplication {
                              title
                            }
                            ... on ScriptDiscountApplication {
                              title
                            }
                          }
                        }
                      }
                      displayFinancialStatus
                      displayFulfillmentStatus
                      lineItems(first: 10) {
                        edges {
                          node {
                            title
                            quantity
                            customAttributes {
                              key
                              value
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        variables = {"query": f"email:{email}", "cursor": cursor}
        result = self._execute_query(query, variables)
        
        customers = result.get("data", {}).get("customers", {}).get("edges", [])
        if not customers:
            return None
            
        node = customers[0]["node"]
        orders_data = node.get("orders") or {}
        page_info = orders_data.get("pageInfo") or {}
        
        # Formatar pedidos
        formatted_orders = []
        for order_edge in orders_data.get("edges") or []:
            order = order_edge.get("node") or {}
            
            # Captura descontos
            discount_titles = []
            for disc_edge in (order.get("discountApplications") or {}).get("edges") or []:
                disc = disc_edge.get("node") or {}
                title = disc.get("code") or disc.get("title")
                if title:
                    discount_titles.append(title)

            # Processar itens e buscar seriais de Tokens
            items_list = []
            serials_found = []
            
            for item_edge in (order.get("lineItems") or {}).get("edges") or []:
                item = item_edge.get("node") or {}
                title = item.get("title", "")
                qty = item.get("quantity", 0)
                
                # Texto do item (ex: 2x Produto)
                items_list.append(f"{qty}x {title}")

                # Se for um TOKEN, busca o serial nas propriedades (customAttributes)
                if "token" in title.lower():
                    attrs = item.get("customAttributes") or []
                    for attr in attrs:
                        if attr.get("key", "").strip() == "360 Serial Number" and attr.get("value"):
                            serials_found.append(f"{title}: {attr['value']}")

            total_price_set = order.get("totalPriceSet") or {}
            presentment_money = total_price_set.get("presentmentMoney") or {}
            
            subtotal_price_set = order.get("subtotalPriceSet") or {}
            subtotal_money = subtotal_price_set.get("presentmentMoney") or {}

            discount_price_set = order.get("totalDiscountsSet") or {}
            discount_money = discount_price_set.get("presentmentMoney") or {}

            formatted_orders.append({
                "name": order.get("name", "N/D"),
                "date": order.get("createdAt", ""),
                "subtotal": subtotal_money.get("amount", "0.00"),
                "total": presentment_money.get("amount", "0.00"),
                "currency": presentment_money.get("currencyCode", "BRL"),
                "discount_amount": discount_money.get("amount", "0.00"),
                "discount_codes": discount_titles,
                "financial_status": order.get("displayFinancialStatus", ""),
                "fulfillment_status": order.get("displayFulfillmentStatus", ""),
                "items_summary": ", ".join(items_list),
                "token_serials": serials_found
            })
            
        amount_spent_obj = node.get("amountSpent") or {}
        marketing_consent = node.get("emailMarketingConsent") or {}

        return {
            "id": node.get("id"),
            "name": node.get("displayName"),
            "email": node.get("email"),
            "phone": node.get("phone"),
            "created_at": node.get("createdAt"),
            "note": node.get("note"),
            "tags": node.get("tags") or [],
            "verified_email": node.get("verifiedEmail"),
            "orders_count": node.get("numberOfOrders"),
            "total_spent": amount_spent_obj.get("amount", "0.00"),
            "marketing_status": marketing_consent.get("marketingState"),
            "addresses": node.get("addresses") or [],
            "orders": formatted_orders,
            "has_next_page": page_info.get("hasNextPage", False),
            "end_cursor": page_info.get("endCursor", None)
        }

    def list_products(self) -> list[str]:
        """
        Busca uma lista de títulos de produtos da loja.
        """
        query = """
        query {
          products(first: 250) {
            edges {
              node {
                title
              }
            }
          }
        }
        """
        result = self._execute_query(query)
        edges = result.get("data", {}).get("products", {}).get("edges", [])
        return sorted(list(set(edge["node"]["title"] for edge in edges)))

    def list_customers(self, cursor: Optional[str] = None, limit: int = 50) -> dict:
        """
        Lista clientes com paginação.
        """
        query = """
        query listCustomers($first: Int!, $after: String) {
          customers(first: $first, after: $after) {
            pageInfo {
              hasNextPage
              endCursor
            }
            edges {
              node {
                id
                firstName
                lastName
                displayName
                email
                phone
                createdAt
                note
                addresses {
                  address1
                  address2
                  city
                  provinceCode
                  zip
                  country
                }
              }
            }
          }
        }
        """
        variables = {"first": limit, "after": cursor}
        result = self._execute_query(query, variables)
        
        customers_data = result.get("data", {}).get("customers", {})
        page_info = customers_data.get("pageInfo", {})
        edges = customers_data.get("edges", [])
        
        customers = []
        for edge in edges:
            node = edge["node"]
            customers.append({
                "id": node.get("id"),
                "first_name": node.get("firstName"),
                "last_name": node.get("lastName"),
                "display_name": node.get("displayName"),
                "email": node.get("email"),
                "phone": node.get("phone"),
                "created_at": node.get("createdAt"),
                "addresses": node.get("addresses") or []
            })
            
        return {
            "customers": customers,
            "has_next_page": page_info.get("hasNextPage", False),
            "end_cursor": page_info.get("endCursor", None)
        }

    def search_customers(self, query: str, first: int = 50) -> list[str]:
        """
        Busca clientes no Shopify que atendam a uma query (ex: 'total_spent:>500')
        e retorna uma lista de e-mails.
        """
        gql = """
        query search($query: String!, $first: Int!) {
          customers(first: $first, query: $query) {
            edges {
              node {
                email
              }
            }
          }
        }
        """
        variables = {"query": query, "first": first}
        result = self._execute_query(gql, variables)
        edges = result.get("data", {}).get("customers", {}).get("edges", [])
        return [edge["node"]["email"] for edge in edges if edge.get("node", {}).get("email")]
