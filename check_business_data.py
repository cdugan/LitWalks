import pickle

# Load the pickled graph
with open('graph_prebuilt.pkl', 'rb') as f:
    data = pickle.load(f)

G, lights, businesses, bbox = data

print(f"Total businesses: {len(businesses)}")
print(f"\nFirst 3 businesses:")
for i, biz in enumerate(businesses[:3]):
    print(f"\nBusiness {i+1}:")
    print(f"  Tuple length: {len(biz)}")
    print(f"  Full data: {biz}")
    if len(biz) > 4:
        print(f"  Hours field type: {type(biz[4])}")
        print(f"  Hours field value: {biz[4]}")
        print(f"  Hours is empty list: {biz[4] == []}")
