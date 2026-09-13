"""Product service."""

from app.models import Product
from app.schemas.product import ProductCreate, ProductUpdate
from app.services.base import CRUDService


class ProductService(CRUDService[Product, ProductCreate, ProductUpdate]):
    model = Product
    label = "Product"
