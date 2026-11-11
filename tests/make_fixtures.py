"""Builds a fake WP REST API page from real Nordex release text (trimmed) for offline tests."""
import json
HDR = '<table border="0"><tr><td><p>Nordex SE</p><p> / Key word(s): {kw}</p><p></p><p>{title}</p><p>{d} / 07:30 CET/CEST</p><p>The issuer is solely responsible for the content of this announcement.</p><hr /><div>'
FTR = ('<p><b>About {cust}</b><br />{cust} is headquartered in Austria and active in 12 countries.</p>'
       '<p><b>About the Nordex Group</b><br />The Group has commissioned more than 67 GW of wind power capacity in over 40 markets.</p>'
       '<p><u>Contact person for press:</u><br />Nordex SE<br />Felix Losada</p></div><hr /><p>Dissemination of a Corporate News, transmitted by EQS News.</p></td></tr></table>')
def post(i, date, slug, title, kw, body, cust="Customer"):
    return {"id": i, "date": date, "link": f"https://www.nordex-online.com/en/{date[:4]}/{date[5:7]}/{slug}/",
            "title": {"rendered": title},
            "content": {"rendered": HDR.format(kw=kw, title=title, d=date[:10]) + body + FTR.format(cust=cust)}}
P = [
 post(204801, "2026-11-09T05:30:04", "nordex-group-to-enter-albania-with-84-mw-order-from-verbund",
      "Nordex Group to enter Albania with 84 MW order from Verbund", "Incoming Orders",
      "<p><b>Hamburg, 9 November 2026.</b> The Nordex Group is entering the Albanian market for the first time. The company has received an order from Austrian energy company VERBUND for the supply and installation of twelve N163/6.X wind turbines for an 84 MW wind farm, project Spille, in Albania. The contract also includes a 15-year Premium Service agreement.</p><p>In January 2026, the companies signed a multi-year framework agreement covering the potential supply of up to 700 MW of wind turbines for projects in six European markets.</p>", "VERBUND"),
 post(204783, "2026-10-27T06:30:04", "nordex-group-to-supply-denkerwulf-with-turbines-for-a-51-mw-wind-farm-in-schleswig-holstein-germany",
      "Nordex Group to supply DenkerWulf with turbines for a 51 MW wind farm in Schleswig-Holstein, Germany", "Incoming Orders",
      "<p><b>Hamburg, 27 October 2026.</b> For the Bredenbek wind farm, DenkerWulf has ordered nine N149/5.X wind turbines with a total capacity of 51.3 MW from the Nordex Group.</p><p>As recently as the end of 2025, Nordex received orders from DenkerWulf totalling more than 122 MW for three wind farms.</p>", "DenkerWulf"),
 post(204759, "2026-10-22T05:30:04", "nordex-group-enters-new-zealand-market-with-192-mw-order-from-mercury",
      "Nordex Group enters New Zealand market with 192 MW order from Mercury", "Incoming Orders",
      "<p><b>Hamburg, 22 October 2026.</b> Mercury has ordered 40 N133/4.8 wind turbines with a total capacity of 192 MW for a wind farm in the Otago region of New Zealand's South Island.</p>", "Mercury"),
 post(204754, "2026-10-20T12:15:21", "blackrock-inc-wilmington-delaware-united-states-of-america-usa-31",
      "BlackRock, Inc., Wilmington, Delaware, United States of America (USA)", "", "<p>Notification of Major Holdings</p>"),
 post(204700, "2026-10-12T05:00:00", "nordex-group-order-intake-rises-29-5-to-2-8-gw-in-the-third-quarter-of-2026",
      "Nordex Group order intake rises 29.5% to 2.8 GW in the third quarter of 2026", "Incoming Orders",
      "<p>Nine-month order intake reaches 7.7 GW. In Q3 2026 the Nordex Group received orders of 2.8 GW.</p>"),
 post(204701, "2026-10-12T05:05:00", "nordex-se-nordex-group-order-intake-rises-29-5-to-2-8-gw-in-the-third-quarter-of-2026",
      "Nordex SE: Nordex Group order intake rises 29.5% to 2.8 GW in the third quarter of 2026", "Incoming Orders",
      "<p>Nine-month order intake reaches 7.7 GW. In Q3 2026 the Nordex Group received orders of 2.8 GW.</p>"),
 post(203100, "2026-01-08T05:30:00", "nordex-obtains-orders-for-414-mw-in-france-belgium-and-portugal",
      "Nordex obtains orders for 414 MW in France, Belgium and Portugal", "Incoming Orders",
      "<p>At the end of the year 2025, the Nordex Group secured further significant orders for 15 wind energy projects in France, Belgium and Portugal. These projects represent with 78 turbines a total capacity of more than 414 MW. The names of the customers and the wind farms are not disclosed.</p>"),
 post(203050, "2025-12-30T05:30:00", "nordex-group-receives-orders-from-uka-totaling-224-mw-for-projects-in-germany",
      "Nordex Group receives orders from UKA totaling 224 MW for projects in Germany", "Incoming Orders",
      "<p>In December 2025, the Nordex Group received orders from UKA for a total of 33 N175/6.X turbines in Germany with a total output of 224.4 MW, part of an existing framework agreement.</p>", "UKA"),
 post(203200, "2026-02-03T05:30:00", "uka-orders-recap",
      "Nordex Group recaps UKA orders of 224 MW in Germany", "Incoming Orders",
      "<p>As reported, UKA ordered 33 N175/6.X turbines with 224.4 MW in Germany in December 2025.</p>", "UKA"),
]
json.dump(P, open("fixtures/api_page.json", "w"), indent=1)

# What a good LLM answer looks like for each fixture (used by the fake client)
A = {
 "Nordex Group to enter Albania": {"release_type":"single_order","orders":[{"mw":84,"mw_is_approximate":False,"mw_text":"84 MW","turbine_count":12,"turbine_model":"N163/6.X","country":"Albania","customer":"VERBUND","wind_farm":"Spille","previously_announced":False,"firmed_period_text":None}],"headline_total_mw":84},
 "Nordex Group to supply DenkerWulf": {"release_type":"single_order","orders":[{"mw":51.3,"mw_is_approximate":False,"mw_text":"51.3 MW","turbine_count":9,"turbine_model":"N149/5.X","country":"Germany","customer":"DenkerWulf","wind_farm":"Bredenbek","previously_announced":False,"firmed_period_text":None}],"headline_total_mw":51.3},
 "Nordex Group enters New Zealand": {"release_type":"single_order","orders":[{"mw":192,"mw_is_approximate":False,"mw_text":"192 MW","turbine_count":40,"turbine_model":"N133/4.8","country":"New Zealand","customer":"Mercury","wind_farm":None,"previously_announced":False,"firmed_period_text":None}],"headline_total_mw":192},
 "Nordex Group order intake rises": {"release_type":"intake_summary","orders":[],"intake_figures":[{"period":"Q3 2026","gw":2.8},{"period":"9M 2026","gw":7.7}]},
 "Nordex SE: Nordex Group order intake rises": {"release_type":"intake_summary","orders":[],"intake_figures":[{"period":"Q3 2026","gw":2.8}]},
 "Nordex obtains orders for 414 MW": {"release_type":"multi_order","orders":[{"mw":414,"mw_is_approximate":True,"mw_text":"more than 414 MW","turbine_count":78,"turbine_model":None,"country":"France, Belgium, Portugal","customer":None,"wind_farm":None,"previously_announced":False,"firmed_period_text":"end of the year 2025"}],"headline_total_mw":414},
 "Nordex Group receives orders from UKA": {"release_type":"single_order","orders":[{"mw":224.4,"mw_is_approximate":False,"mw_text":"224.4 MW","turbine_count":33,"turbine_model":"N175/6.X","country":"Germany","customer":"UKA","wind_farm":None,"previously_announced":False,"firmed_period_text":"December 2025"}]},
 "Nordex Group recaps UKA": {"release_type":"single_order","orders":[{"mw":224.4,"mw_is_approximate":False,"mw_text":"224.4 MW","turbine_count":33,"turbine_model":"N175/6.X","country":"Germany","customer":"UKA","wind_farm":None,"previously_announced":False,"firmed_period_text":"December 2025"}]},
}
json.dump(A, open("fixtures/llm_answers.json", "w"), indent=1)
print("fixtures written")
