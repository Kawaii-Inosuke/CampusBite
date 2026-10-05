# Menu transcription: please check these

The menus were read from the photos in this folder (`Evergreen_*` were rotated
upright first with `rotate_photos.py`). Everything below is a judgement call
or a hard-to-read spot. Fix any wrong price in the JSON **before** seeding, or
afterwards on the manager's Menu page. (`seed_menus.py` never overwrites an
existing item, so editing the JSON after seeding changes nothing.)

## Evergreen (Java Green Food Court)

1. **Price column is offset by about one row** in several panels (perspective of
   the photo): Egg items, North Indian Veg Curry, Starters, Chinese Side Dish,
   Shawarma plates, Tandoori Bread. In every panel the number of prices equals
   the number of items, and the last item has no price on its own line, so the
   prices were matched **in order**. Most worth a spot check:
   - Dal Fry 70, Dal Tadka 80
   - Gobi Masala 100, Aloo Masala 90
   - Channa Masala 100, Paneer Butter Masala 120, Kadai Paneer 100
   - Paneer Kofta 120, Paneer Masala 100
   - Egg Keema Masala 90, Egg Bhurji 40, Egg Roast 70, **Egg Pepper Fry 30** (looks low)
   - Roti 15, Butter Roti 20, Naan 15, Butter Naan 20, Tandoori Porota 20
2. **"Szchewan RICE / NOODLES / PASTA : +10.00"**: read as "the Schezwan version
   of any fried rice / noodles / pasta costs ₹10 more". Created 27 items
   (9 bases × rice/noodles/pasta) in their own category "Schezwan Rice /
   Noodles / Pasta". Sweet Corn rice/noodles/pasta were not given a Schezwan
   version. If the shop does not offer all of these, mark them unavailable.
3. **One price for "X fried Rice / Noodles / Pasta"** was split into three items
   at the same price (e.g. Chicken Fried Rice, Chicken Noodles, Chicken Pasta, all ₹90).
4. **"Veg. / Non / Hakka Noodles ₹100"** became two items: Veg Hakka Noodles and
   Non-Veg Hakka Noodles, both ₹100.
5. **Chicken Dry Fry ₹110** is at the top of a panel with no heading; it was put
   in "Curry Non-Veg".
6. **Shawarma plates** (also offset): Double Spl. Plate 180, **Cheese Double Spl.
   Plate 190**, Cheese Double Plate 180, Spicy Double Spl. Plate 180, Spicy
   Cheese Double Spl. Plate 180.
7. **Duplicates skipped**: "Veg. Pulav" and "Gobi Pulav" (Rice section, ₹100) are
   the same as Veg Pulao / Gobi Pulao in Biriyani (₹100). "Chees Shwarma Roll ₹70"
   is the same as Cheese Shwarma Roll ₹70.
8. "Sweet Corn **Chi** Pasta" read as Sweet Corn Chicken Pasta. "Paneer Kimma Roll"
   as Paneer Keema Roll. "140 00" / "100 00" read as 140 / 100.
9. Spellings were normalised: Shwarma → Shawarma, Munchurian → Manchurian,
   Mugal → Mughal, Hydrabadi → Hyderabadi, Peppar → Pepper, Chi. → Chicken,
   Panner → Paneer, Buter → Butter.

## Muskan Food Point

1. **Paneer Stuffed Roti ₹150**: clearly printed, but much higher than the other
   rotis (₹25 to ₹50). Could be a misprint for ₹50.
2. "Tandoori chicken / Full, Half 540-260" → Tandoori Chicken (Full) ₹540 and (Half) ₹260.
   "Butter Chicken Full / Half 350/170" → (Full) ₹350 and (Half) ₹170.
3. "Plain Naan, Butter Naan ₹50": one price for two breads, both set to ₹50.
4. "Mushroom ₹160" under Tandoori Items → named "Tandoori Mushroom".
5. "Hani Chilly Paneer / Potato" → Honey Chilli Paneer / Potato.
6. "Crusted Paneer Masala" kept as printed (maybe "Crushed").
7. Paneer Manchurian Gravy ₹160 is cheaper than Paneer Manchurian Dry ₹180: as printed.
8. The roti/naan list has no printed heading → category "Roti and Naan".
   The first "Tandoori" heading lists only kulchas → "Tandoori and Kulcha".
9. There is no "+10 for non-veg" note on the Muskan menu.
