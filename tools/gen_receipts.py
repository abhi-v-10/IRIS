"""Generate synthetic receipts (image + ground truth) for prototype evaluation."""
import random, json, os, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter
random.seed(7)
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "DejaVuSansMono.ttf")   # bundled: works on Windows too
STORES = {
 "Groceries": ["FreshMart Supermarket","Daily Basket Stores","GreenLeaf Organics","Metro Kirana Mart"],
 "Dining": ["Spice Route Restaurant","Cafe Aroma","Biryani House","Urban Tadka"],
 "Transport": ["QuickCab Rides","Metro Fuel Station","CityBus Pass Centre"],
 "Electronics": ["Digital Hub Electronics","Gadget World","Circuit Point"],
 "Health": ["CarePlus Pharmacy","Wellness Medico","HealthFirst Chemist"],
 "Utilities": ["PowerGrid Electricity Board","AirNet Broadband","AquaSupply Services"],
}
ITEMS = {
 "Groceries": [("Basmati Rice 5kg",640),("Toned Milk 1L",56),("Whole Wheat Atta",285),("Sugar 1kg",48),("Tea Powder",210),("Eggs Dozen",84),("Tomato 1kg",40)],
 "Dining": [("Paneer Butter Masala",280),("Veg Biryani",220),("Butter Naan",45),("Cold Coffee",130),("Masala Dosa",110),("Gulab Jamun",90)],
 "Transport": [("Ride Fare",240),("Petrol 5L",520),("Monthly Pass",900),("Toll Charge",80)],
 "Electronics": [("USB Cable",299),("Wireless Mouse",699),("Phone Case",349),("Power Bank",1499)],
 "Health": [("Paracetamol Strip",32),("Vitamin C Tablets",180),("Hand Sanitizer",95),("Cough Syrup",120)],
 "Utilities": [("Electricity Bill",1450),("Broadband Plan",799),("Water Charges",320)],
}
def make(i):
    cat = random.choice(list(STORES))
    store = random.choice(STORES[cat])
    n = random.randint(2,5)
    items = random.sample(ITEMS[cat], min(n,len(ITEMS[cat])))
    rows=[]; total=0
    for name,price in items:
        q = random.choice([1,1,2,3]) if cat in("Groceries","Dining") else 1
        amt=price*q; rows.append((name,q,amt)); total+=amt
    tax=round(total*0.05,2); grand=round(total+tax,2)
    d=(random.randint(1,28),random.randint(1,12),2026)
    style=random.choice(["%02d/%02d/%04d","%02d-%02d-%04d"])
    date=style%d
    return dict(id=i,category=cat,store=store,date=f"{d[2]:04d}-{d[1]:02d}-{d[0]:02d}",date_text=date,
                items=[dict(name=n,qty=q,amount=a) for n,q,a in rows],subtotal=float(total),tax=tax,total=grand)
def render(r,noise):
    W=520; lines=[r["store"].upper(),"GSTIN: 36ABCDE1234F1Z5","Date: "+r["date_text"],"Bill No: %05d"%random.randint(1000,99999),"-"*34]
    for it in r["items"]:
        nm=it["name"][:20]; lines.append("%-20s %d x %8.2f"%(nm,it["qty"],it["amount"]/it["qty"]) if False else "%-20s %2d %10.2f"%(nm,it["qty"],it["amount"]))
    lines+=["-"*34,"%-23s %10.2f"%("Subtotal",r["subtotal"]),"%-23s %10.2f"%("GST 5%",r["tax"]),"%-23s %10.2f"%("TOTAL",r["total"]),"-"*34,"Thank you! Visit again"]
    f=ImageFont.truetype(FONT,20); H=60+len(lines)*30
    img=Image.new("L",(W,H),255); dr=ImageDraw.Draw(img)
    for k,l in enumerate(lines): dr.text((20,30+k*30),l,font=f,fill=20)
    if noise=="blur": img=img.filter(ImageFilter.GaussianBlur(1.2))
    if noise=="rotate": img=img.rotate(random.uniform(-3,3),expand=True,fillcolor=255)
    if noise=="speckle":
        import numpy as np
        a=np.array(img).astype(int); a+=np.random.default_rng(random.randint(0,10**9)).normal(0,28,a.shape).astype(int); img=Image.fromarray(a.clip(0,255).astype("uint8"))
    return img
if __name__=="__main__":
    OUT=sys.argv[1] if len(sys.argv)>1 else "data"; os.makedirs(OUT,exist_ok=True); gt=[]
    for i in range(60):
        r=make(i); r["noise"]=["clean","blur","rotate","speckle"][i%4]
        render(r,r["noise"]).save(os.path.join(OUT,f"r{i:03d}.png")); gt.append(r)
    json.dump(gt,open(os.path.join(OUT,"gt.json"),"w"),indent=1); print("generated",len(gt))
