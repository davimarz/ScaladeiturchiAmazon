"""Conservative duplicate detection, preserving size/model differences in titles."""
import re
import unicodedata
from urllib.parse import urlsplit

def keys(product):
 result=set()
 asin=str(product.get('asin') or '').strip().upper()
 if asin:result.add(('asin',asin))
 title=unicodedata.normalize('NFKC',str(product.get('titolo') or '')).casefold()
 title=' '.join(re.findall(r'\w+',title))
 image=urlsplit(str(product.get('immagine_url') or '')).path
 image=re.sub(r'\._[^/]+_\.', '.', image)
 if len(title.split())>=4 and image:
  result.add(('identity',title,image))
 return result

def unique(products):
 seen=set();result=[]
 for product in products:
  identity=keys(product)
  if identity & seen:continue
  seen.update(identity);result.append(product)
 return result

def already_present(product, products):
 identity=keys(product)
 return any(identity & keys(other) for other in products)
