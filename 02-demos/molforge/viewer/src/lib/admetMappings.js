/*
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * ADMET endpoint metadata.
 *
 * Maps each endpoint key (as returned by ADMET-AI in our screening_results dicts)
 * to:
 *   - displayName: human label
 *   - percentileKey: the matching key in drugbank_percentiles for the
 *     `_drugbank_approved_percentile` lookup (suffix added at use site)
 *   - direction: 'higher_better' | 'lower_better' | 'context'
 *     Used to color the percentile bar marker accordingly.
 *   - description: short tooltip-style explanation
 */

export const ENDPOINT_GROUPS = [
  {
    id: 'absorption',
    label: 'Absorption',
    icon: 'A',
    endpoints: [
      { key: 'caco2_permeability', displayName: 'Caco-2 Permeability', percentileKey: 'Caco2_Wang', direction: 'context', description: 'Intestinal absorption (log units, more positive = better)' },
      { key: 'hia', displayName: 'Human Intestinal Absorption', percentileKey: 'HIA_Hou', direction: 'higher_better', description: 'Probability of high intestinal absorption' },
      // One card per underlying model. ADMET-AI predicts P-gp *inhibition* and
      // F > 20% only; there is no substrate or F30 model, so showing those as
      // separate cards would repeat the same number under a different name.
      { key: 'pgp_inhibitor', displayName: 'P-glycoprotein Inhibitor', percentileKey: 'Pgp_Broccatelli', direction: 'context', description: 'Likelihood of inhibiting Pgp efflux transporter' },
      { key: 'bioavailability_f20', displayName: 'Bioavailability (F20%)', percentileKey: 'Bioavailability_Ma', direction: 'higher_better', description: 'Probability of >20% oral bioavailability' },
    ],
  },
  {
    id: 'distribution',
    label: 'Distribution',
    icon: 'D',
    endpoints: [
      { key: 'bbb_penetration', displayName: 'Blood-Brain Barrier Penetration', percentileKey: 'BBB_Martins', direction: 'context', description: 'Probability of crossing the BBB (CNS targets want high, peripheral targets want low)' },
      { key: 'ppb', displayName: 'Plasma Protein Binding (%)', percentileKey: 'PPBR_AZ', direction: 'context', description: 'Percentage bound to plasma proteins' },
      { key: 'vdss', displayName: 'Volume of Distribution (VDss)', percentileKey: 'VDss_Lombardo', direction: 'context', description: 'Steady-state volume of distribution (log L/kg)' },
    ],
  },
  {
    id: 'metabolism',
    label: 'Metabolism',
    icon: 'M',
    endpoints: [
      { key: 'cyp1a2_inhibitor', displayName: 'CYP1A2 Inhibitor', percentileKey: 'CYP1A2_Veith', direction: 'lower_better', description: 'Risk of inhibiting CYP1A2 (drug-drug interaction)' },
      { key: 'cyp2c9_inhibitor', displayName: 'CYP2C9 Inhibitor', percentileKey: 'CYP2C9_Veith', direction: 'lower_better', description: 'Risk of inhibiting CYP2C9 (warfarin interactions)' },
      { key: 'cyp2c19_inhibitor', displayName: 'CYP2C19 Inhibitor', percentileKey: 'CYP2C19_Veith', direction: 'lower_better', description: 'Risk of inhibiting CYP2C19' },
      { key: 'cyp2d6_inhibitor', displayName: 'CYP2D6 Inhibitor', percentileKey: 'CYP2D6_Veith', direction: 'lower_better', description: 'Risk of inhibiting CYP2D6' },
      { key: 'cyp3a4_inhibitor', displayName: 'CYP3A4 Inhibitor', percentileKey: 'CYP3A4_Veith', direction: 'lower_better', description: 'Risk of inhibiting CYP3A4 (most drugs metabolize through this)' },
      { key: 'cyp2c9_substrate', displayName: 'CYP2C9 Substrate', percentileKey: 'CYP2C9_Substrate_CarbonMangels', direction: 'context', description: 'Likelihood of being metabolized by CYP2C9' },
      { key: 'cyp2d6_substrate', displayName: 'CYP2D6 Substrate', percentileKey: 'CYP2D6_Substrate_CarbonMangels', direction: 'context', description: 'Likelihood of being metabolized by CYP2D6' },
      { key: 'cyp3a4_substrate', displayName: 'CYP3A4 Substrate', percentileKey: 'CYP3A4_Substrate_CarbonMangels', direction: 'context', description: 'Likelihood of being metabolized by CYP3A4' },
    ],
  },
  {
    id: 'excretion',
    label: 'Excretion',
    icon: 'E',
    endpoints: [
      { key: 'half_life', displayName: 'Half-Life (log h)', percentileKey: 'Half_Life_Obach', direction: 'context', description: 'Predicted plasma half-life (log hours)' },
      { key: 'clearance_hepatocyte', displayName: 'Hepatocyte Clearance', percentileKey: 'Clearance_Hepatocyte_AZ', direction: 'context', description: 'Hepatocyte clearance rate' },
      { key: 'clearance_microsome', displayName: 'Microsome Clearance', percentileKey: 'Clearance_Microsome_AZ', direction: 'context', description: 'Microsomal clearance rate' },
    ],
  },
  {
    id: 'toxicity',
    label: 'Toxicity',
    icon: 'T',
    endpoints: [
      { key: 'herg_inhibitor', displayName: 'hERG Inhibitor', percentileKey: 'hERG', direction: 'lower_better', description: 'Cardiotoxicity risk via hERG channel blockade' },
      { key: 'ames_mutagenicity', displayName: 'AMES Mutagenicity', percentileKey: 'AMES', direction: 'lower_better', description: 'Bacterial reverse-mutation test (genotoxicity)' },
      { key: 'dili', displayName: 'Drug-Induced Liver Injury (DILI)', percentileKey: 'DILI', direction: 'lower_better', description: 'Risk of drug-induced liver injury' },
      { key: 'ld50', displayName: 'LD50 (log mol/kg)', percentileKey: 'LD50_Zhu', direction: 'higher_better', description: 'Acute toxicity (higher = safer)' },
      { key: 'skin_sensitization', displayName: 'Skin Sensitization', percentileKey: 'Skin_Reaction', direction: 'lower_better', description: 'Risk of skin sensitization reactions' },
      { key: 'carcinogenicity', displayName: 'Carcinogenicity', percentileKey: 'Carcinogens_Lagunin', direction: 'lower_better', description: 'Carcinogenic potential' },
      { key: 'clinical_toxicity', displayName: 'Clinical Toxicity', percentileKey: 'ClinTox', direction: 'lower_better', description: 'Probability of clinical trial toxicity failure' },
    ],
  },
]

/**
 * Look up the DrugBank-approved-drugs percentile for an endpoint
 * from a molecule's drugbank_percentiles dict.
 */
export function lookupPercentile(percentileKey, drugbankPercentiles) {
  if (!drugbankPercentiles) return null
  const fullKey = `${percentileKey}_drugbank_approved_percentile`
  const v = drugbankPercentiles[fullKey]
  return typeof v === 'number' ? v : null
}

/**
 * Format a raw value for display.
 */
export function formatValue(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v !== 'number') return String(v)
  if (Math.abs(v) >= 100) return v.toFixed(1)
  if (Math.abs(v) >= 10) return v.toFixed(2)
  if (Math.abs(v) >= 0.01) return v.toFixed(3)
  return v.toExponential(2)
}
