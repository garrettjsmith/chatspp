"""
SPP API Client for GMB Gorilla
Handles fetching orders, tickets, and messages from Service Provider Pro
"""

import os
import requests
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass


@dataclass
class Message:
    id: int
    user_id: int
    created_at: datetime
    message: str
    staff_only: bool
    files: list


@dataclass
class Client:
    id: int
    name_f: str
    name_l: str
    email: str
    
    @property
    def full_name(self) -> str:
        return f"{self.name_f} {self.name_l}".strip()


@dataclass
class Order:
    id: int
    status: str
    service: str
    service_id: int
    user_id: int
    client: Client
    employees: list  # assigned managers
    last_message_at: datetime
    created_at: datetime
    note: str
    form_data: dict
    tags: list


@dataclass 
class Ticket:
    id: int
    status: str
    subject: str
    user_id: int
    client: Client
    employees: list
    last_message_at: datetime
    created_at: datetime
    note: str
    form_data: dict
    tags: list
    order_id: Optional[int]


class SPPClient:
    """Client for interacting with Service Provider Pro API"""
    
    def __init__(self, workspace_url: str = None, api_key: str = None):
        self.workspace_url = workspace_url or os.getenv("SPP_WORKSPACE_URL", "gmbgorilla.spp.co")
        self.api_key = api_key or os.getenv("SPP_API_KEY")
        
        if not self.api_key:
            raise ValueError("SPP_API_KEY environment variable required")
        
        self.base_url = f"https://{self.workspace_url}/api"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Api-Version": "2024-03-05"
        }
    
    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make authenticated request to SPP API"""
        url = f"{self.base_url}/{endpoint}"
        response = requests.request(method, url, headers=self.headers, **kwargs)
        response.raise_for_status()
        return response.json()
    
    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse ISO datetime string"""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except:
            return None
    
    def _parse_client(self, data: dict) -> Client:
        """Parse client data from API response"""
        return Client(
            id=data.get('id', 0),
            name_f=data.get('name_f', ''),
            name_l=data.get('name_l', ''),
            email=data.get('email', '')
        )
    
    def _parse_message(self, data: dict) -> Message:
        """Parse message data from API response"""
        return Message(
            id=data['id'],
            user_id=data['user_id'],
            created_at=self._parse_datetime(data['created_at']),
            message=data['message'],
            staff_only=data.get('staff_only', False),
            files=data.get('files', [])
        )
    
    # =========================================================================
    # ORDERS
    # =========================================================================
    
    def list_orders(
        self,
        limit: int = 50,
        page: int = 1,
        sort: str = "last_message_at:desc",
        filters: dict = None
    ) -> list[Order]:
        """
        List all orders, sorted by last message time by default.
        
        Args:
            limit: Items per page (max 100)
            page: Page number
            sort: Sort field and direction (e.g. "last_message_at:desc")
            filters: Optional filters dict
        """
        params = {
            "limit": limit,
            "page": page,
            "sort": sort
        }
        
        if filters:
            for key, value in filters.items():
                params[f"filters[{key}]"] = value
        
        response = self._request("GET", "orders", params=params)
        
        orders = []
        for item in response.get('data', []):
            orders.append(Order(
                id=item['id'],
                status=item['status'],
                service=item['service'],
                service_id=item['service_id'],
                user_id=item['user_id'],
                client=self._parse_client(item.get('client', {})),
                employees=item.get('employees', []),
                last_message_at=self._parse_datetime(item.get('last_message_at')),
                created_at=self._parse_datetime(item['created_at']),
                note=item.get('note', ''),
                form_data=item.get('form_data', {}),
                tags=item.get('tags', [])
            ))
        
        return orders
    
    def get_order(self, order_id: int) -> Order:
        """Get detailed order information"""
        response = self._request("GET", f"orders/{order_id}")
        item = response
        
        return Order(
            id=item['id'],
            status=item['status'],
            service=item['service'],
            service_id=item['service_id'],
            user_id=item['user_id'],
            client=self._parse_client(item.get('client', {})),
            employees=item.get('employees', []),
            last_message_at=self._parse_datetime(item.get('last_message_at')),
            created_at=self._parse_datetime(item['created_at']),
            note=item.get('note', ''),
            form_data=item.get('form_data', {}),
            tags=item.get('tags', [])
        )
    
    def get_order_messages(self, order_id: int, limit: int = 50) -> list[Message]:
        """Get messages for an order (newest first)"""
        response = self._request("GET", f"order_messages/{order_id}", params={"limit": limit})
        return [self._parse_message(m) for m in response.get('data', [])]
    
    def send_order_message(
        self,
        order_id: int,
        message: str,
        user_id: int = None,
        staff_only: bool = False
    ) -> dict:
        """
        Send a message to an order.
        
        Args:
            order_id: The order ID
            message: Message content
            user_id: User ID to send as (assigned manager)
            staff_only: If True, only visible to staff
        """
        payload = {
            "message": message,
            "staff_only": staff_only
        }
        if user_id:
            payload["user_id"] = user_id
        
        return self._request("POST", f"order_messages/{order_id}", json=payload)
    
    # =========================================================================
    # TICKETS
    # =========================================================================
    
    def list_tickets(
        self,
        limit: int = 50,
        page: int = 1,
        sort: str = "last_message_at:desc",
        filters: dict = None
    ) -> list[Ticket]:
        """List all tickets, sorted by last message time by default"""
        params = {
            "limit": limit,
            "page": page,
            "sort": sort
        }
        
        if filters:
            for key, value in filters.items():
                params[f"filters[{key}]"] = value
        
        response = self._request("GET", "tickets", params=params)
        
        tickets = []
        for item in response.get('data', []):
            tickets.append(Ticket(
                id=item['id'],
                status=item['status'],
                subject=item['subject'],
                user_id=item['user_id'],
                client=self._parse_client(item.get('client', {})),
                employees=item.get('employees', []),
                last_message_at=self._parse_datetime(item.get('last_message_at')),
                created_at=self._parse_datetime(item['created_at']),
                note=item.get('note', ''),
                form_data=item.get('form_data', {}),
                tags=item.get('tags', []),
                order_id=item.get('order_id')
            ))
        
        return tickets
    
    def get_ticket(self, ticket_id: int) -> Ticket:
        """Get detailed ticket information"""
        response = self._request("GET", f"tickets/{ticket_id}")
        item = response
        
        return Ticket(
            id=item['id'],
            status=item['status'],
            subject=item['subject'],
            user_id=item['user_id'],
            client=self._parse_client(item.get('client', {})),
            employees=item.get('employees', []),
            last_message_at=self._parse_datetime(item.get('last_message_at')),
            created_at=self._parse_datetime(item['created_at']),
            note=item.get('note', ''),
            form_data=item.get('form_data', {}),
            tags=item.get('tags', []),
            order_id=item.get('order_id')
        )
    
    def get_ticket_messages(self, ticket_id: int, limit: int = 50) -> list[Message]:
        """Get messages for a ticket (newest first)"""
        response = self._request("GET", f"ticket_messages/{ticket_id}", params={"limit": limit})
        return [self._parse_message(m) for m in response.get('data', [])]
    
    def send_ticket_message(
        self,
        ticket_id: int,
        message: str,
        user_id: int = None,
        staff_only: bool = False
    ) -> dict:
        """Send a message to a ticket"""
        payload = {
            "message": message,
            "staff_only": staff_only
        }
        if user_id:
            payload["user_id"] = user_id
        
        return self._request("POST", f"ticket_messages/{ticket_id}", json=payload)
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    
    def find_items_needing_reply(
        self,
        check_orders: bool = True,
        check_tickets: bool = True,
        hours_lookback: int = 24
    ) -> list[dict]:
        """
        Find orders and tickets where the last message was from the client.
        
        Returns list of dicts with:
            - type: 'order' or 'ticket'
            - item: Order or Ticket object
            - messages: list of Message objects (newest first)
            - client_message: the client message needing reply
            - manager_user_id: assigned manager's user_id for sending reply
        """
        needs_reply = []
        cutoff = datetime.now(tz=None) - timedelta(hours=hours_lookback)
        
        if check_orders:
            orders = self.list_orders(limit=100, sort="last_message_at:desc")
            for order in orders:
                # Skip if no recent activity
                if order.last_message_at and order.last_message_at.replace(tzinfo=None) < cutoff:
                    continue
                
                messages = self.get_order_messages(order.id)
                if not messages:
                    continue
                
                # Check if last non-staff-only message is from client
                for msg in messages:
                    if msg.staff_only:
                        continue
                    
                    # If message is from client (user_id matches order's user_id)
                    if msg.user_id == order.user_id:
                        # Get manager user_id from employees
                        manager_id = None
                        if order.employees:
                            manager_id = order.employees[0].get('id')
                        
                        needs_reply.append({
                            'type': 'order',
                            'item': order,
                            'messages': messages,
                            'client_message': msg,
                            'manager_user_id': manager_id
                        })
                    break  # Only check the most recent non-staff message
        
        if check_tickets:
            tickets = self.list_tickets(limit=100, sort="last_message_at:desc")
            for ticket in tickets:
                # Skip closed tickets
                if ticket.status.lower() in ['closed', 'resolved']:
                    continue
                
                # Skip if no recent activity
                if ticket.last_message_at and ticket.last_message_at.replace(tzinfo=None) < cutoff:
                    continue
                
                messages = self.get_ticket_messages(ticket.id)
                if not messages:
                    continue
                
                for msg in messages:
                    if msg.staff_only:
                        continue
                    
                    if msg.user_id == ticket.user_id:
                        manager_id = None
                        if ticket.employees:
                            manager_id = ticket.employees[0].get('id')
                        
                        needs_reply.append({
                            'type': 'ticket',
                            'item': ticket,
                            'messages': messages,
                            'client_message': msg,
                            'manager_user_id': manager_id
                        })
                    break
        
        return needs_reply


if __name__ == "__main__":
    # Quick test
    client = SPPClient()
    print("Testing SPP connection...")
    
    orders = client.list_orders(limit=5)
    print(f"Found {len(orders)} recent orders")
    
    tickets = client.list_tickets(limit=5)
    print(f"Found {len(tickets)} recent tickets")
    
    needs_reply = client.find_items_needing_reply(hours_lookback=48)
    print(f"Found {len(needs_reply)} items needing reply")
