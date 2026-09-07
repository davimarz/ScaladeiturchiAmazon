"""Recognize a Prime badge only inside a product delivery block."""
from html.parser import HTMLParser
import re

DELIVERY_IDS = {'deliveryBlockMessage','deliveryMessageMirId','mir-layout-DELIVERY_BLOCK',
 'mir-layout-DELIVERY_BLOCK-slot-PRIMARY_DELIVERY_MESSAGE_LARGE',
 'mir-layout-DELIVERY_BLOCK-slot-SECONDARY_DELIVERY_MESSAGE_LARGE',
 'delivery-message','delivery-block','deliveryBlock_feature_div'}
VOID={'img','input','meta','link','br','hr','source','area','base','embed','param','wbr'}

class Parser(HTMLParser):
 def __init__(self):
  super().__init__();self.stack=[];self.badge=False;self.asins=set()
 def handle_starttag(self,tag,attributes):
  attrs=dict(attributes);identifier=attrs.get('id','')
  active=any(scope for _,scope in self.stack) or identifier in DELIVERY_IDS
  classes=attrs.get('class','').split()
  label=(attrs.get('aria-label') or attrs.get('alt') or '').strip().casefold()
  if active and ('a-icon-prime' in classes or (tag=='img' and label in {'prime','amazon prime'}) or label in {'prime','amazon prime'}):
   self.badge=True
  if tag=='input' and (attrs.get('name')=='ASIN' or identifier=='ASIN'):
   self.asins.add(attrs.get('value','').upper())
  if tag not in VOID:self.stack.append((tag,active))
 def handle_endtag(self,tag):
  for i in range(len(self.stack)-1,-1,-1):
   if self.stack[i][0]==tag:
    del self.stack[i:];break

def confirmed(html,asin):
 parser=Parser();parser.feed(html or '')
 if parser.asins and asin.upper() not in parser.asins:return False
 return parser.badge
