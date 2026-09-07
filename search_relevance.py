"""Conservative title relevance: aliases, required terms, accessory intent."""
import re
import unicodedata

ALIASES = {
 'notebook': {'notebook','laptop','portatile','portatili'},
 'smartphone': {'smartphone','cellulare','cellulari','telefonino'},
 'cuffie': {'cuffie','auricolari','headphones','earbuds'},
}
STOP = {'per','con','da','di','il','lo','la','le','gli','un','una','e','a','al','del','della','the','offerte','offerta','amazon','giorno','tecnologia'}
ACCESSORIES = {'adesivi','adesivo','custodia','custodie','cover','borsa','borse','pellicola','pellicole','supporto','supporti','caricatore','alimentatore','batteria','ricambio','ricambi','sleeve','sticker','stickers'}


def tokens(text):
 text=unicodedata.normalize('NFKD',str(text or '').casefold())
 return re.findall(r'[a-z0-9]+', ''.join(c for c in text if not unicodedata.combining(c)))


def matches(query, title):
 q=tokens(query); t=tokens(title); ts=set(t)
 if not q:return True
 groups=[]
 for word in q:
  if word in STOP:continue
  if word in {'pc','computer'} and any(w in ALIASES['notebook'] for w in q):continue
  group=next((values for values in ALIASES.values() if word in values),{word})
  if group not in groups:groups.append(group)
 if not all(ts.intersection(group) for group in groups):return False
 # Searching a complete notebook must not return a compatible accessory.
 if any(w in ALIASES['notebook'] for w in q) and not set(q).intersection(ACCESSORIES):
  device_positions=[i for i,w in enumerate(t) if w in ALIASES['notebook']]
  accessory_positions=[i for i,w in enumerate(t) if w in ACCESSORIES]
  if accessory_positions and device_positions and min(accessory_positions)<min(device_positions):return False
  if re.search(r'\b(?:per|for|compatibile con)\s+(?:pc\s+)?(?:notebook|laptop|portatil[ei])\b',' '.join(t)):return False
 return True
