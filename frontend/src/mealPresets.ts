/**
 * Editable Indian meal presets for the what-if strip.
 *
 * The carbohydrate values are APPROXIMATE, ILLUSTRATIVE ASSUMPTIONS, rounded to the middle of values published
 * by different nutrition tables (to the nearest 5 g, or 1 g where that matches a two-item serving). Real values vary widely with recipe and portion. Ranges seen across sources,
 * checked 2026-10-21:
 *   - 2 idli: 14 g (Indian Nutrient Databank recipe, small idli, via nnwa.in) to 26 g (nutrimacro.in, 100 g)
 *   - 1 plain dosa: 20 g (rozmac.com, 60 g) to 32 g (nutrimacro.in, 100 g)
 *   - 1 masala dosa: about 48 g (nutrimacro.in, 200 g)
 *   - 1 cup cooked white rice: about 44.5 g (fithealthregimen.com, 158 g)
 *   - 1 chapati: about 18 g (rozmac.com and fithealthregimen.com, 40 g)
 *   - 1 plate poha: 38 g (rozmac.com, 150 g) to 44 g (organicmandya.com, 230 g)
 *   - 1 bowl upma: 28 g (rozmac.com, 150 g) to 38 g (nutrimacro.in, 200 g)
 * These are not clinical nutrition advice. The forecasting models only receive grams of carbohydrate:
 * food type, fibre, fat, protein and glycaemic index are NOT model inputs.
 */
export interface MealPreset {
  id: string;
  label: string;
  serving: string;
  carbs: number; // grams, editable after selection
  range: [number, number]; // lowest and highest value in the sources above (equal when only one source)
}

export const MEAL_PRESETS: readonly MealPreset[] = [
  { id: "idli2", label: "Idli with sambar", serving: "2 idli + 1 small bowl sambar", carbs: 35, range: [14, 46] },
  { id: "dosa", label: "Plain dosa", serving: "1 medium dosa", carbs: 25, range: [20, 32] },
  { id: "masala-dosa", label: "Masala dosa", serving: "1 dosa with potato filling (~200 g)", carbs: 50, range: [48, 48] },
  { id: "poha", label: "Kanda poha", serving: "1 plate (~200 g)", carbs: 40, range: [38, 44] },
  { id: "upma", label: "Rava upma", serving: "1 bowl (~150–200 g)", carbs: 35, range: [28, 38] },
  { id: "chapati2", label: "Chapati", serving: "2 chapati (~40 g each)", carbs: 36, range: [36, 36] },
  { id: "rice", label: "White rice", serving: "1 cup cooked (~160 g)", carbs: 45, range: [44.5, 44.5] },
];

export const PRESET_NOTE =
  "Approximate, illustrative carb values (published values vary with recipe and portion). Edit the grams before simulating. " +
  "The model only sees grams of carbohydrate, not food type, fibre, fat or glycaemic index.";

export function presetById(id: string): MealPreset | undefined {
  return MEAL_PRESETS.find((p) => p.id === id);
}

/** Label shown in the scenario table: keep the preset name only while the grams still equal the preset value. */
export function scenarioLabel(grams: number, presetId: string | null): string | null {
  const p = presetId ? presetById(presetId) : undefined;
  return p && p.carbs === grams ? `${p.label} (${p.serving}, approx.)` : null;
}
