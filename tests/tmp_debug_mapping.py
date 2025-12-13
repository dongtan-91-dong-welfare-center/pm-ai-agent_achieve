import tools, data_loader
from pprint import pprint

tools.DB = data_loader.load_master_data()
plan_df = tools.DB.get('production_plan')
print('Plan columns:', plan_df.columns.tolist())
print('First plan row:', plan_df.iloc[0].to_dict())
row0 = plan_df.iloc[0]
country = row0.get('country')
packing = row0.get('packing_unit')
print('Country:', country, 'Packing:', packing)
ppcm = tools.DB.get('prod_plan_code_map')
print('ppcm columns:', ppcm.columns.tolist())
mapped_by_pack = ppcm[ppcm['packing_unit'] == packing] if 'packing_unit' in ppcm.columns else ppcm
print('Mapped by packing count:', len(mapped_by_pack))
if len(mapped_by_pack) > 0:
    pprint(mapped_by_pack.iloc[0].to_dict())
    mapped_by_pack_country = mapped_by_pack[mapped_by_pack['country'] == country] if 'country' in ppcm.columns and country else mapped_by_pack
    print('Filtered by country count:', len(mapped_by_pack_country))
    if len(mapped_by_pack_country) > 0:
        pprint(mapped_by_pack_country.iloc[0].to_dict())
else:
    print('No mapped entries for packing unit.')
