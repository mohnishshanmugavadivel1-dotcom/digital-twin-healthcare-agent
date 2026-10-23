/**
 * Editable Indian meal presets for the what-if strip: 24 dishes grouped by region.
 *
 * CARBOHYDRATES are APPROXIMATE, ILLUSTRATIVE values. Real values vary widely with recipe and portion.
 * Each preset states its basis:
 *  - "cited": rounded to the middle of values published by different nutrition tables; `range` is the lowest and
 *    highest value seen (checked 2026-10-21 and 2026-10-23):
 *      2 idli: 14 g (Indian Nutrient Databank recipe, small idli, via nnwa.in) to 26 g (nutrimacro.in, 100 g);
 *      1 plain dosa: 20 g (rozmac.com, 60 g) to 32 g (nutrimacro.in, 100 g);
 *      1 masala dosa: about 48 g (nutrimacro.in, 200 g);
 *      1 cup cooked white rice: about 44.5 g (fithealthregimen.com, 158 g);
 *      1 chapati: about 18 g (rozmac.com and fithealthregimen.com, 40 g);
 *      1 plate poha: 38 g (rozmac.com, 150 g) to 44 g (organicmandya.com, 230 g);
 *      1 bowl upma: 28 g (rozmac.com, 150 g) to 38 g (nutrimacro.in, 200 g);
 *      2 thepla: 26 g (tarladalal.com, 13.0 g per thepla) to 30 g (eatthismuch.com, 2 pieces, 64 g);
 *      litti chokha, 1 serving: 50 g (snapcalorie.com, 250 g) to 67.7 g (tarladalal.com, per serving);
 *      2 appam with vegetable stew: 40 g (homepressurecooking.com) to 50 g (nutribit.app, 300 g);
 *      1 medium samosa: 22 g (eatthismuch.com, 71 g) to 22.4 g (eatbetter.app, 70 g).
 *  - "team_estimate": a value from the team's brief, NOT checked against a nutrition table (no source range).
 *
 * GI BADGES are INDICATIVE, taken from the main carbohydrate source in Table 1 of Atkinson, Foster-Powell and
 * Brand-Miller, "International tables of glycemic index and glycemic load values: 2008", Diabetes Care
 * 31:2281-2283 (doi:10.2337/dc08-1239): white rice, boiled 73; rice porridge/congee 78; white wheat bread 75;
 * wheat roti 62; chapatti 52; millet porridge 67; chickpeas 28; kidney beans 24 (low <= 55, high >= 70).
 * The dish itself was not measured; recipe, fat, fibre, protein and portion change the response, and published
 * values for the same Indian dish differ widely between studies. "mixed" = components in different bands.
 *
 * Not clinical nutrition advice. The forecasting models and the research curve receive ONLY grams of
 * carbohydrate: food type, fibre, fat, protein and glycaemic index are NOT inputs.
 */
export type Region = "South" | "North" | "West" | "East" | "Snacks & beverages";
export type GiBand = "low" | "low-medium" | "medium" | "high" | "mixed" | "not listed";

export interface MealPreset {
  id: string;
  label: string;
  region: Region;
  serving: string;
  carbs: number; // grams, editable after selection
  basis: "cited" | "team_estimate";
  range: [number, number] | null; // cited presets: lowest and highest source value; team estimates: null
  gi: GiBand;
  giNote: string; // which Atkinson 2008 entry the indicative band comes from
}

const RICE = "white rice, boiled: GI 73";
export const MEAL_PRESETS: readonly MealPreset[] = [
  // South
  { id: "idli2", label: "Idli with sambar", region: "South", serving: "2 idli + 1 small bowl sambar", carbs: 35, basis: "cited", range: [14, 46], gi: "high", giNote: `rice batter (${RICE})` },
  { id: "dosa", label: "Plain dosa", region: "South", serving: "1 medium dosa", carbs: 25, basis: "cited", range: [20, 32], gi: "high", giNote: `rice batter (${RICE})` },
  { id: "masala-dosa", label: "Masala dosa", region: "South", serving: "1 dosa with potato filling (~200 g)", carbs: 50, basis: "cited", range: [48, 48], gi: "high", giNote: `rice batter (${RICE})` },
  { id: "upma", label: "Rava upma", region: "South", serving: "1 bowl (~150–200 g)", carbs: 35, basis: "cited", range: [28, 38], gi: "not listed", giNote: "semolina dish: no Table 1 entry" },
  { id: "rice", label: "White rice", region: "South", serving: "1 cup cooked (~160 g)", carbs: 45, basis: "cited", range: [44.5, 44.5], gi: "high", giNote: RICE },
  { id: "appam-stew", label: "Appam with vegetable stew", region: "South", serving: "2 appam + 1 bowl stew", carbs: 45, basis: "cited", range: [40, 50], gi: "high", giNote: `rice batter (${RICE})` },
  { id: "pongal", label: "Ven pongal", region: "South", serving: "1 bowl", carbs: 52, basis: "team_estimate", range: null, gi: "high", giNote: "rice and moong dal porridge (rice porridge/congee: GI 78)" },
  { id: "curd-rice", label: "Curd rice", region: "South", serving: "1 bowl", carbs: 45, basis: "team_estimate", range: null, gi: "high", giNote: `${RICE}; curd may lower the response` },
  { id: "ragi-mudde", label: "Ragi mudde", region: "South", serving: "1 ball with saaru", carbs: 44, basis: "team_estimate", range: null, gi: "medium", giNote: "finger millet (millet porridge: GI 67)" },
  { id: "biryani", label: "Hyderabadi biryani", region: "South", serving: "1 plate", carbs: 92, basis: "team_estimate", range: null, gi: "high", giNote: `${RICE}; basmati is often lower` },
  // North
  { id: "chapati2", label: "Chapati", region: "North", serving: "2 chapati (~40 g each)", carbs: 36, basis: "cited", range: [36, 36], gi: "low-medium", giNote: "chapatti: GI 52; wheat roti: GI 62" },
  { id: "phulka-dal", label: "Phulka with dal tadka", region: "North", serving: "2 phulka + 1 bowl dal", carbs: 48, basis: "team_estimate", range: null, gi: "low-medium", giNote: "chapatti 52 / wheat roti 62; lentils are low GI" },
  { id: "rajma-chawal", label: "Rajma chawal", region: "North", serving: "1 plate", carbs: 68, basis: "team_estimate", range: null, gi: "mixed", giNote: `kidney beans: GI 24; ${RICE}` },
  { id: "chole-bhature", label: "Chole bhature", region: "North", serving: "2 bhature + 1 bowl chole", carbs: 78, basis: "team_estimate", range: null, gi: "mixed", giNote: "chickpeas: GI 28; refined-wheat bread (white wheat bread: GI 75)" },
  { id: "aloo-paratha", label: "Aloo paratha", region: "North", serving: "1 paratha with curd", carbs: 58, basis: "team_estimate", range: null, gi: "mixed", giNote: "wheat flatbread (GI 52–62) with potato filling" },
  // West
  { id: "poha", label: "Kanda poha", region: "West", serving: "1 plate (~200 g)", carbs: 40, basis: "cited", range: [38, 44], gi: "high", giNote: `flattened rice (${RICE})` },
  { id: "thepla2", label: "Methi thepla", region: "West", serving: "2 thepla", carbs: 28, basis: "cited", range: [26, 30], gi: "low-medium", giNote: "wheat flatbread (chapatti 52 / wheat roti 62)" },
  { id: "dhokla", label: "Khaman dhokla", region: "West", serving: "4 pieces", carbs: 32, basis: "team_estimate", range: null, gi: "low", giNote: "gram flour (chickpeas: GI 28)" },
  { id: "pav-bhaji", label: "Pav bhaji", region: "West", serving: "2 pav + 1 bowl bhaji", carbs: 65, basis: "team_estimate", range: null, gi: "high", giNote: "soft white bread (white wheat bread: GI 75) with potato" },
  { id: "bajra-roti", label: "Bajra roti with sabzi", region: "West", serving: "2 roti + 1 bowl sabzi", carbs: 40, basis: "team_estimate", range: null, gi: "medium", giNote: "pearl millet (millet porridge: GI 67)" },
  // East
  { id: "machher-jhol", label: "Machher jhol with rice", region: "East", serving: "1 plate", carbs: 64, basis: "team_estimate", range: null, gi: "high", giNote: RICE },
  { id: "litti-chokha", label: "Litti chokha", region: "East", serving: "2 litti + chokha", carbs: 60, basis: "cited", range: [50, 67.7], gi: "mixed", giNote: "wheat and roasted-gram filling with potato/brinjal chokha" },
  // Snacks and beverages
  { id: "chai-biscuits", label: "Masala chai with biscuits", region: "Snacks & beverages", serving: "1 cup + 2 biscuits", carbs: 18, basis: "team_estimate", range: null, gi: "mixed", giNote: "milk: GI 39; sugar and biscuits are higher" },
  { id: "samosa", label: "Samosa", region: "Snacks & beverages", serving: "1 medium (~70 g)", carbs: 22, basis: "cited", range: [22, 22.4], gi: "mixed", giNote: "refined-wheat pastry with potato filling" },
];

export const REGIONS: readonly Region[] = ["South", "North", "West", "East", "Snacks & beverages"];

export const GI_LABEL: Record<GiBand, string> = {
  low: "Low GI", "low-medium": "Low–medium GI", medium: "Medium GI", high: "High GI", mixed: "Mixed GI",
  "not listed": "GI not listed",
};

export const PRESET_NOTE =
  "Approximate, illustrative carb values (published values vary with recipe and portion; some are team estimates, " +
  "marked as such). Edit the grams before simulating. GI badges are indicative, from the main carbohydrate in the " +
  "2008 international GI tables; the dish itself was not measured. " +
  "The model only sees grams of carbohydrate, not food type, fibre, fat or glycaemic index.";

export function presetById(id: string): MealPreset | undefined {
  return MEAL_PRESETS.find((p) => p.id === id);
}

export function presetTitle(p: MealPreset): string {
  const basis = p.basis === "cited" ? `cited range ${p.range![0]}–${p.range![1]} g` : "team estimate, not source-verified";
  return `${p.label}: ${p.serving} ≈ ${p.carbs} g carbs (${basis}). ${GI_LABEL[p.gi]} (indicative: ${p.giNote}).`;
}

/** Distinct carbohydrate amounts of all presets (the static export records each of them). */
export function presetGrams(): number[] {
  return [...new Set(MEAL_PRESETS.map((p) => p.carbs))].sort((a, b) => a - b);
}

/** Label shown in the scenario table: keep the preset name only while the grams still equal the preset value. */
export function scenarioLabel(grams: number, presetId: string | null): string | null {
  const p = presetId ? presetById(presetId) : undefined;
  return p && p.carbs === grams ? `${p.label} (${p.serving}, approx.)` : null;
}
