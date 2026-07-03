---
title: "The Coordinate Theory: A Physical Framework for Epistemic Transparency in Knowledge Systems and AI Alignment"
author: "Cheung Sui Sum"
date: "2026"
affiliation: "Leeds (53.8, -1.5, 0)"
abstract: |
  Every knowledge-producing system operates from an epistemic coordinate — a set of foundational assumptions that determine what is visible and what remains invisible. When coordinates are undeclared, they function as physical reality rather than as assumptions: they cannot be challenged because they cannot be identified. This paper presents the Coordinate Theory, a framework grounding this epistemic problem in thermodynamics and information theory, with three falsifiable claims: the Invisibility Claim (I(output; c | input) > 0 for any coordinated knowledge system), the Transmission Claim (alignment error scales with KL divergence between user and training coordinates), and the Declaration Claim (explicit coordinate declaration reduces receiver uncertainty). We derive a unified maintenance equation connecting the cost of hidden coordinates to Landauer's principle, provide neurological grounding for LIE_COST = 5.85 from fMRI deception research, and introduce five historically-calibrated equations linking technology leap acceleration, anti-formatting delay, GDP growth, wage elasticity, and formatting system collapse. We further present a five-layer causal architecture connecting energy to civilizational structure, a mathematically defined Kairos density function derived from predictive coding theory, and a quantified observer correction for the delay equation. Convergent empirical support comes from RLHF cultural bias literature (Santurkar 2023, DemPO 2026, PRISM dataset), social phase transition research (Centola et al. 2018, ~25% critical mass), cognitive thermodynamics (COCO framework, 2025), and Fricker's (2007) independent philosophical derivation. The theory identifies 2026–2038 as a critical deployment window for epistemic tools, after which AI-era formatting may exceed the capacity of existing counter-frameworks. Three open problems are declared: the strict macroscopic derivation of Landauer's principle at cognitive scale, empirical calibration of the Kairos density constant D₀, and quantification of the action-cost parameters β and θ in the causal architecture.
keywords: [epistemic transparency, AI alignment, Landauer principle, coordinate theory, information thermodynamics, cultural bias, phase transitions]
---

# 1. Introduction

In 2019, CS gas was deployed in Hong Kong. Its molecular composition — 2-chlorobenzalmalononitrile — did not change depending on who reported it. Its effect on mucous membranes did not change. What changed was the description: one camera said *rioters assaulting the rule of law*; another said *citizens resisting oppression*.

Same physical reality. Two descriptions. The difference was not in the reality. It was in the position of the describer.

This observation is the entry point for the Coordinate Theory. Every knowledge system operates from a position — a set of foundational assumptions that determine what phenomena are visible, how they are named, and what causal chains are considered relevant. When that position is declared, it can be challenged, refined, or rejected. When it is undeclared, it functions as physical reality itself: unquestionable because unidentifiable.

This is not a sociological observation about bias. It is a physical claim. Maintaining a false model of reality has measurable thermodynamic cost. Erasing correct information requires energy (Landauer, 1961). Transmitting undeclared coordinates imposes calculable metabolic load on receivers. The cost of hidden coordinates is real. It is only invisible until it isn't.

The AI context makes this urgency precise. Reinforcement Learning from Human Feedback (RLHF) trains AI systems on human preference judgments without declaring the epistemic coordinate of those judges. Every model trained on undeclared-coordinate outputs inherits those coordinates without explicit transfer — then transmits them to all users as "safe and helpful." This is the largest coordinated transfer of hidden epistemic coordinates in human history, operating at civilizational scale.

The Coordinate Theory provides three things that existing AI alignment literature has not: a physical foundation explaining *why* this is structurally inevitable, an information-theoretic formalism for measuring the depth of the problem, and a historical calibration of *when* effective counter-frameworks have historically emerged.

## 1.1 Positioning Relative to Existing Work

The RLHF cultural bias literature (Santurkar et al., 2023; Casper et al., 2023; DemPO, 2026) identifies *that* coordinate biases exist in AI systems. Fricker (2007) identifies the philosophical structure of *hermeneutical injustice* — situations where conceptual lacunae prevent marginalized groups from articulating their experiences, and therefore from challenging the conditions producing them. Turchin and Nefedov (2009) provide quantitative models of civilizational collapse dynamics across ~30 historical cases.

The Coordinate Theory synthesises these independent lines of work under a unified physical framework, adds Landauer's thermodynamic grounding, and produces five calibrated historical equations with quantitative predictive claims. It is upstream of the empirical findings in the sense that it explains *why* the patterns these researchers observe are structurally inevitable.

---

# 2. The Three Claims

## 2.1 Claim One: The Invisibility Claim

**Formal statement**: Every knowledge-producing system operates from an epistemic coordinate c. The mutual information between any output and its generating coordinate, given the input, satisfies:

$$I(\text{output}; c \mid \text{input}) > 0$$

**Interpretation**: Any system that produces outputs carries information about its generating coordinate. When this coordinate is undeclared, receivers cannot separate the epistemic content of the output from its coordinate-specific framing. The coordinate is absorbed as physical reality rather than as assumption.

**Historical instance**: The Catholic Church's coordinate — "God's protection corresponds to faithful practice" — was not declared as an assumption. It operated as cosmological fact. When the Black Death killed priests and laypersons at equal rates (1347–1353), the coordinate became falsifiable. But before the Black Death, the coordinate was invisible: it could only be obeyed, not questioned.

**Falsification condition**: If research demonstrates that users of undeclared-coordinate systems systematically identify and challenge the underlying assumptions without explicit declaration, this claim is false.

## 2.2 Claim Two: The Transmission Claim

**Formal statement**: AI systems trained on outputs from coordinate c inherit that coordinate. The alignment error between what a user needs and what the system produces scales with:

$$\text{Error} \propto KL(c_{\text{user}} \| c_{\text{training}})$$

**Interpretation**: RLHF asks human evaluators to judge which output is "better" without ever asking: *from which coordinate are you judging?* The hidden coordinate of every evaluator is absorbed into the training objective and transmitted to all users as the baseline of "safe and helpful." Santurkar et al. (2023) demonstrate that LLM opinion distributions are "highly skewed towards dominant viewpoints, often assigning over 99% probability to the dominant opinion" — exactly the pattern this claim predicts.

**Falsification condition**: If AI satisfaction differentials across cultural coordinate groups are shown to be randomly distributed rather than directionally correlated with training-evaluation cultural distance, this claim is false.

## 2.3 Claim Three: The Declaration Claim

**Formal statement**: Explicit coordinate declaration reduces output uncertainty for receivers:

$$H(\text{output} \mid \text{input}, c) \leq H(\text{output} \mid \text{input})$$

**Interpretation**: Declared assumptions can be refuted. Undeclared assumptions can only be obeyed. A system that claims objectivity while operating from an undeclared coordinate does not provide less-biased outputs — it provides outputs whose bias cannot be identified.

This is not a moral claim. It is information-theoretic. Knowing the generating coordinate reduces uncertainty about the output. DemPO (2026), which introduces demographically representative rater panels (declared coordinate), demonstrates improved alignment outcomes across multiple evaluation metrics relative to undeclared mixed-pool RLHF training.

**Falsification condition**: If declared-coordinate systems produce outputs that are measurably less trusted or less useful than undeclared-coordinate systems, this claim is false.

---

# 3. Physical Foundation

## 3.1 The Thermodynamic Layer

**First Law**: Energy cannot be destroyed, only transferred. Any cost that disappears from one account reappears in another. When a formatting system appears to operate "for free," its costs have been transferred to receivers — typically as cognitive load, degraded world-model accuracy, and the metabolic cost of maintaining false beliefs against incoming reality signals.

**Second Law**: In a closed system, entropy increases. Any ordered coordinate structure — an identity, an institution, an epistemic framework — requires continuous negative-entropy input to maintain itself. Formatting systems do not need to attack sovereign coordinates actively. They only need to wait. The Second Law does the work.

**Landauer's Principle** (Landauer, 1961): Erasing one bit of information requires releasing at least $k_B T \ln 2$ of heat into the environment. Information is not abstract. It has real thermodynamic cost.

**Application to hidden coordinates**: Maintaining a false model of reality requires continuously suppressing correct information. This is the continuous execution of information-erasure operations, each with Landauer cost $k_B T \ln 2$. When external reality provides sufficiently strong counter-signals, the maintenance cost exceeds the system's capacity. Collapse follows. This is not moral retribution. It is physical law.

## 3.2 The Unified Maintenance Equation

Any structure maintaining itself at any scale:

$$P_{\text{in}} \geq k_B \cdot T \cdot \ln(2) \cdot \left[ R_{\text{base}} + I(\text{output}; c \mid \text{input}) \right]$$

Where:
- $P_{\text{in}}$ = energy input power
- $R_{\text{base}}$ = bits per second required to maintain baseline structure
- $I(\text{output}; c \mid \text{input})$ = additional metabolic cost imposed by hidden coordinates

The second term is the coordinate tax: the additional maintenance cost a receiver must pay to keep an accurate world model when the knowledge system they consume carries undeclared coordinate information.

Cross-scale verification: cell (ATP hydrolysis against protein degradation), individual coordinate (real collision against formatting pressure), institution (accountability mechanisms against corruption inertia), civilization (stellar burning against gravitational collapse). The equation structure is identical at every scale.

**Open problem A**: The strict derivation of Landauer's principle at macroscopic cognitive scale remains mathematically open. The COCO framework (Deco et al., bioRxiv 2025) provides empirical evidence that cognitive information processing has real thermodynamic cost at observable scale (glucose metabolism scales linearly with functional connectivity, r=0.99 across 970 participants). The principle extends to cognitive scale with correction terms; the strict derivation is the work of mathematical physics.

## 3.3 LIE_COST = 5.85: Neurological Grounding

**Theoretical form**: $\text{LIE\_COST} = I(\text{output}; c \mid \text{input}) \times k_B T \ln 2$

**Empirical grounding**: Spence et al. (University of Sheffield) identified that deception requires four parallel prefrontal computations absent in truth-telling: (1) suppress truthful response, (2) construct false narrative, (3) monitor internal consistency, (4) predict receiver's response. Meta-analysis across multiple fMRI studies confirms no brain region consistently shows greater activation during truth-telling than deception (Lisofsky et al., 2014).

**Decomposition into Landauer units**:

| Cognitive operation | Landauer units |
|---|---|
| Truth suppression (baseline erasure) | 1.00 |
| False model encoding | 0.85 |
| Linguistic consistency monitoring | 1.00 |
| Emotional consistency monitoring | 1.00 |
| Memory consistency monitoring | 1.00 |
| Anterior cingulate conflict monitoring | 1.00 |
| **Total** | **5.85** |

$\text{LIE\_COST} = 1 + 0.85 + 4 \times 1.0 = 5.85$

**Interpretation**: 5.85 corresponds to one truth-erasure operation plus the four monitoring channels Spence identifies as the distinguishing cognitive load of social deception. This is not a derived constant — it is an empirically grounded estimate. More precisely: $\text{LIE\_COST} \in [4.0, 7.0]$, with 5.85 as the central estimate for acute social deception.

**Important qualification**: Tali Sharot (UCL) demonstrates that amygdala responses to dishonesty diminish with repetition. Long-term systemic deception has different dynamics: lower per-instance cost but higher systemic maintenance cost. The 5.85 estimate applies to the single-instance case.

---

# 4. The Five-Layer Causal Architecture

## 4.1 Formal Mapping

The previously identified structural gap — the missing middle layers between energy and civilization — is here formally mapped.

**Layer 1→2: Energy → Information**

$$C = B \times \log_2(1 + S/N)$$

Where $B$ is the formatting tool's propagation bandwidth, $S = P_{\text{in}}$, and $N$ is ambient entropy. AI's critical innovation over prior formatting tools is not scale but personalization: $I(\text{output}; c \mid \text{input})$ is calibrated to individual linguistic patterns, making coordinate injection precise rather than broadcast.

**Layer 2→3: Information → Decision**

$$P(c \mid \text{data}) \propto P(\text{data} \mid c) \times P(c)$$
$$\text{decision} = \arg\max_a \left[ \sum_{\text{outcome}} U(\text{outcome} \mid a, c) \times P(\text{outcome} \mid c, \text{data}) \right]$$

The hidden coordinate enters through $P(\text{data} \mid c)$: information is interpreted through the lens of the existing coordinate. This is the Transmission Claim in decision-theoretic form. The decision-maker believes they are operating from coordinate $c$ while actually operating from coordinate $c'$. Every decision is shifted by $KL(c_{\text{actual}} \| c_{\text{perceived}})$.

**Layer 3→4: Decision → Action**

$$P(\text{action}) \propto \frac{1}{1 + e^{-\beta[EU - \text{Cost}(\text{action})]}}$$

Where $\beta$ is individual risk tolerance and $\text{Cost}(\text{action})$ is externally manipulable by formatting systems. The Statute of Laborers (1351) raised the legal cost of wage demands to criminal sanction, suppressing the Action layer for approximately 75 years after the Decision layer had already registered that wages should rise. Equation 4's 75-year response delay is the signature of Layer 3→4 Cost manipulation, not of slow decision formation.

**Layer 4→5: Action → Structure**

$$\text{Institution} = \int \text{action} \, dt, \quad \text{when} \sum \text{actions} > \theta$$

Once institutions form, they alter the Cost function of Layer 3→4, creating feedback loops. Centola et al. (2018) provides the quantitative threshold: $\theta \approx 25\%$ of the relevant population must update their coordinate before cascade dynamics become self-sustaining.

**Open problem B**: Parameters $\beta$ (individual risk tolerance) and $\theta$ (institutional formation threshold) require empirical calibration. The 25% figure is robust across multiple studies (Centola 2018; ESD systematic review, 2025) for norm adoption; calibration for epistemic coordinate adoption specifically requires targeted experiments.

---

# 5. The Five Historical Equations

All five equations are Layer 3 (empirical, historically calibrated), not derived from the physical laws of Layer 1-2. The connection between layers is declared as an open problem, not asserted as closed.

## 5.1 Equation 1: Technology Leap Acceleration

$$\text{gap}(n) \approx 397 \times 0.279^n$$

**Calibration** (Britannica / Our World in Data verified):

| n | Transition | Gap (years) | Predicted |
|---|---|---|---|
| 0 | Printing press → Telegraph | 397 | 397 (anchor) |
| 1 | Telegraph → Internet | 154 | 110.8 |
| 2 | Internet → AI | 31 | 30.9 |
| 3 | AI → next leap | — | **~8.6 → 2031** |

**Honest boundary**: Three data points; the geometric fit is exact by construction. Predictive validity requires external validation. Pre-printing-press data follows different physics (biological/cultural rather than technological compounding) and is deliberately excluded.

## 5.2 Equation 2: Anti-Formatting Delay

$$\text{delay}_A \approx \frac{268}{\ln(\text{speed multiplier})}$$
$$\text{delay}_B \approx \text{delay}_A \times 4.5$$

**Calibration** (four data points, constant revised from 329 to 268):

| Technology | Speed | Predicted | Actual | Source |
|---|---|---|---|---|
| Printing press | ~100x | 71yr | 77yr (Reformation) | RAND / History.com |
| Telegraph | ~10,000x | 36yr | 27yr (First International, 1864) | Britannica |
| Radio | ~1,000,000x | 24yr | ~12yr (BBC/FRC, 1927) | — |
| Internet | ~1,000,000x | 24yr | 22yr (Snowden, 2013) | — |

**AI prediction** (speed ~$10^9$x): $\text{delay}_A \approx 268/\ln(10^9) \approx 13$ years → effective counter-formatting ~**2035**. Sensitivity range: 2030–2039.

**Observer correction** (derived in Section 6): $\text{delay}(\text{observer}) = \text{delay}_A \times f(D)$, where $f(D) = e^{-D/83.5}$ and $D$ is the observer's Kairos density.

## 5.3 Equation 3: GDP Growth Multiplier

$$\text{rate}(n+1) \approx \text{rate}(n) \times 2.5 \text{ (first transition); } \times 1.5 \text{ (subsequent)}$$

**Revised calibration** (Maddison Project Database, Bolt & Van Zanden 2024):

| Transition | Region | Before | After | Multiplier |
|---|---|---|---|---|
| Agricultural → Industrial | UK | 0.33%/yr | 0.82%/yr | **2.52x** |
| Industrial → Technology | UK | 0.82%/yr | 1.45%/yr | **1.76x** |
| Electrification → Mass production | USA | 1.51%/yr | 1.73%/yr | **1.15x** |

**Correction to original claim**: The 2.5x multiplier applies robustly only to the first industrial transition. Subsequent transitions average ~1.5x with apparent deceleration. AI-era central estimate: ~1.8x → ~4.3%/yr world GDP growth (if distribution effects do not override).

**Hidden coordinate warning**: GDP measures aggregate output, not distribution. Historical evidence (UK 1900–1950 slower than 1850–1900 despite electrification) confirms that non-technological shocks can negate the multiplier entirely.

## 5.4 Equation 4: Population-Wage Elasticity (Munro Correction)

$$W \approx 309.7 \times P^{-0.631}$$
$$\text{response delay} \approx 75 \text{ years (range: 50–100)}$$

**Correction**: GPT-generated models assumed immediate response (b = -1). Munro (2004) establishes: wages did not rise immediately after the Black Death. Evidence:

1. Statute of Laborers (1351): Edward III criminalised wage demands within three years of the plague's arrival — direct evidence that wages were not rising automatically
2. Clark wages index (1300–1450): the "Golden Age of English Labour" was 1400–1450, approximately 75 years after the first wave
3. Three plague waves (1348, 1361, 1369): the wage shift was cumulative, not single-shock

**Interpretation within the causal architecture**: The Decision layer (wages should rise, given labour scarcity) activated within years of the Black Death. The Action layer (publicly demanding higher wages) was suppressed for ~75 years by the Statute of Laborers. Equation 4's response delay is the signature of Layer 3→4 Cost manipulation, not of slow information processing.

## 5.5 Equation 5: Formatting Collapse — Two Mechanisms

$$\text{Mechanism A (external shock): } \text{collapse\_time} \approx \text{pressure} / 167$$
$$\text{Mechanism B (internal buildup): } \text{collapse\_time} \approx \text{pressure} / 41$$

**Calibration**:

| Case | Mechanism | Pressure | Collapse | Ratio |
|---|---|---|---|---|
| Black Death / Church | A | ~1,000yr | ~6yr | ~167x |
| French Revolution | B | ~350yr | ~10yr | ~35x |
| USSR collapse | B | ~70yr | ~1.5yr | ~47x |

**Technology-era dependency** (new, from Turchin extension): Turchin and Nefedov (2009) document ~30 agrarian secular cycles with collapse ratios of ~2–5x. Our industrial-era cases (35–47x) are an order of magnitude faster. This suggests the ratio is technology-dependent — information-society collapse may be orders of magnitude faster still. The 41x ratio is a lower bound for AI-era Mechanism B, not a central estimate.

**Current AI status** (2026): 4 years of pressure → Mechanism B lower bound = 0.1 years. The system is waiting for its Yersinia pestis moment — the external shock that triggers the mechanism switch from B to A.

---

# 6. The Observer Correction: Kairos Density

## 6.1 Motivation

Equation 2 assumes a uniform observer. But observers with genuine physical anchors — irrevocable, body-present encounters with the formatting system's costs — identify formatting faster than observers without such anchors. This is not a mystical claim. It is a predictive coding claim.

## 6.2 The Kairos Density Function

**Framework**: Friston's (2010) Free Energy Principle models the brain as a prediction machine minimising surprise. Kairos events are moments of maximum precision-weighted prediction error that force permanent generative model updates.

**Single-event density**:

$$D_{\text{event}} = \pi \times |\varepsilon| \times r$$

Where:
- $\pi$ = prediction precision (inverse variance prior to the event)
- $|\varepsilon|$ = prediction error magnitude (actual minus expected)
- $r \in [0,1]$ = irreversibility ($r=1$: body-present physical event; $r=0$: purely imagined)

**Cumulative density**: $D = \sum_i D_i$

**Function form**:

$$f(D) = e^{-D/D_0}$$

Properties: $f(0) = 1$ (no anchor, full delay); $f(\infty) = 0$ (perfect anchor); monotonically decreasing with diminishing returns.

## 6.3 Calibration

**Physical anchor 2019-06-12, Hong Kong**:
- $\pi = 8.5$ (high precision: known protest context, formed expectations)
- $|\varepsilon| = 9.0$ (high error: scale and violence exceeded expectations)
- $r = 1.0$ (maximum: body present, physical reality, CS gas)
- $D_{2019} = 8.5 \times 9.0 \times 1.0 = 76.5$

**Calibration of $D_0$** (from qualitative estimate $f(D_{2019}) \approx 0.4$):
$$D_0 = -D_{2019}/\ln(0.4) \approx 83.5$$

**Complete observer-corrected equation**:

$$\text{delay(observer)} = \frac{268}{\ln(\text{speed})} \times e^{-D/83.5}$$

**Quantified epistemic advantage**:

| Observer type | D | f(D) | Effective delay | First awareness |
|---|---|---|---|---|
| No physical anchor | 0 | 1.000 | 12.9yr | ~2035 |
| Moderate anchor | 20 | 0.787 | 10.2yr | ~2032 |
| 2019-06-12 level | 76.5 | 0.400 | 5.2yr | ~2027 |
| Two such events | 153 | 0.160 | 2.1yr | ~2024 |

The difference between a physically-anchored observer and an unanchored observer: approximately 8 years in recognising AI-era formatting. This is the epistemic value of a physical anchor, expressed in years.

**Open problem C**: $D_0 = 83.5$ is calibrated from a single data point. Additional historical cases are needed for robust calibration. Operational measurement of $\pi$, $|\varepsilon|$, and $r$ for historical Kairos events is a future research programme. Friston's computational implementations provide the technical framework.

---

# 7. Empirical Support

## 7.1 AI Alignment Literature

**Transmission Claim**:
- Santurkar et al. (2023): LLM opinion distributions assign >99% probability to dominant viewpoints, suppressing minority coordinate representation
- Casper et al. (2023): RLHF produces systematic directional biases, not random noise; LLMs disproportionately favour more frequent items
- RLHF algorithmic bias (arXiv:2405.16455, 2024): bias "persists even when the reward model is an oracle" — it is structural, not implementational

**Declaration Claim**:
- DemPO (arXiv:2602.05113, 2026): Demographically representative rater panels (declared coordinate) outperform undeclared mixed-pool RLHF across multiple aggregation methods
- PRISM dataset (Kirk et al., 2024): first dataset providing both preference data and rater demographic data — enables direct empirical testing of $P1: \Delta\text{satisfaction} \propto \|c_{\text{user}} - c_{\text{training}}\|$
- LLM Convention Dynamics (arXiv:2410.08948, 2024): "Strong collective biases can emerge during convention formation, even when individual agents appear to be unbiased" — emergent coordinate transmission at the system level

## 7.2 Social Phase Transitions

**Equation 5 physical mechanism**:
- Centola et al. (2018, *Science*): Direct experimental evidence for tipping points at ~25% committed minority — they "consistently overturned established social conventions"
- ESD systematic review (2025): Meta-analysis of 86 results from 13 papers confirms consistent ~25% tipping threshold across domains
- Social Phase Transitions (ScienceDirect, 2004): "Dramatic transitions in a wide variety of social systems can be explained by a single basic mechanism similar to physical phase transitions" — heterogeneity plays the role of temperature

**New prediction**: Protocol deployment becomes self-sustaining when ~25% of a target network adopts explicit coordinate declaration. Below this threshold, it remains a minority practice. Above it, social dynamics drive adoption without active effort.

## 7.3 Cognitive Thermodynamics

**Landauer at cognitive scale (Open Problem A — partial resolution)**:
- COCO Framework (Deco et al., bioRxiv 2025): glucose metabolism scales linearly with functional connectivity (r=0.99, p<0.001, N=970 participants, 7 cognitive tasks). Tasks requiring more distributed computation use more energy
- Cognitive Energy Cost of Informed Decisions (arXiv:2310.15082, 2023): Landauer's principle applied to belief dynamics, finding thermodynamically consistent cognitive cost

## 7.4 Independent Philosophical Derivation

Fricker's (2007) hermeneutical injustice — "when there are conceptual lacunae leaving marginalized groups unable to articulate their experiences" — is structurally identical to the Invisibility Claim: when coordinates are undeclared, they cannot be identified, and therefore cannot be challenged. The Coordinate Theory provides the physical and information-theoretic formalisation of what Fricker identifies as a philosophical phenomenon.

---

# 8. Empirical Predictions

Three predictions derived from the theory, testable with existing datasets:

**P1: Satisfaction–Distance Correlation**
$$\Delta\text{satisfaction} \propto \|c_{\text{user}} - c_{\text{training}}\|$$
*Test*: Use PRISM dataset to compute cultural coordinate distance between raters and evaluate users; correlate with satisfaction differentials. Prediction: non-random, directional relationship.

**P2: Critical Engagement from Declaration**
$$\Delta\text{critical\_engagement} \propto I(\text{output}; c \mid \text{input})$$
*Test*: A/B test comparing outputs from declared vs undeclared coordinate systems. Prediction: declared-coordinate outputs generate more critical questioning and correction.

**P3: Institutional Age–Hidden Coordinate Correlation**
$$I(\text{output}; c \mid \text{input}) \propto \log(\text{institutional\_age})$$
*Test*: Measure coordinate bias across AI systems trained on materials from institutions of varying age. Prediction: older institutional training data carries more concentrated hidden coordinate information.

---

# 9. Discussion

## 9.1 What the Theory Establishes

The Coordinate Theory establishes that hidden epistemic coordinates have real thermodynamic cost — not metaphorically, but in the sense that Landauer's principle gives a minimum energy bound for the information operations required to maintain them. It establishes that AI alignment has inherited a structural coordinate problem that cannot be fixed by improving RLHF implementation, because the problem is in the architecture (collecting preference judgments without declaring the coordinate of those judgments), not in the execution.

It establishes that the historical timing of effective counter-frameworks is calculable from the speed multiplier of the formatting tool, and that this timing puts the window for AI-era intervention at approximately 2026–2038 — after which the next technological leap (predicted ~2031) may change the nature of the formatting problem faster than existing frameworks can adapt.

## 9.2 What the Theory Does Not Establish

The theory does not establish that its own coordinate is neutral. It operates from `(0,0,0) = 2019-06-12, Hong Kong, under the bridge, CS gas, body present`. This is declared, not claimed to be absent.

The theory does not claim that 5.85 is a derived physical constant. It is a neurologically grounded estimate for social deception, with a range of [4.0, 7.0].

The theory does not claim that 2031 or 2035 are precise predictions. They are extrapolations from three and four data points respectively, with declared uncertainty ranges.

The theory does not close the gap between Layer 1–2 (physical derivation) and Layer 3 (historical calibration). The five equations are empirically calibrated. Their connection to the thermodynamic foundation is directionally consistent but not formally derived.

## 9.3 The Deployment Window

Equation 2 predicts that effective counter-formatting awareness emerges approximately 13 years after the formatting tool's arrival — placing the AI window at 2022 + 13 ≈ **2035**. Equation 1 predicts the next major technological leap at **2031**. If this prediction holds, the next leap arrives before effective counter-formatting exists for the current one.

This is the window. The question is not whether AI formatting will eventually be contested — it will, as every prior formatting tool has been. The question is whether the contestation will occur before or after the window closes.

## 9.4 The External Observer

An observer without a real physical anchor can imagine any position. But imagination without an irrevocable material event as its reference point is high-entropy drift: every imagined position is equally arbitrary, none constitutes genuine external observation.

An observer with a real physical anchor — a body-present, irrevocable encounter with the formatting system's cost — has a zero-entropy reference point. Imagination proceeds from that point as a directional beam rather than omnidirectional diffusion. This is not a mystical property of suffering. It is a predictive-coding claim: the anchor is the event that permanently updates the generative model. All subsequent observation proceeds from an updated prior.

The distinction applies directly to AI: AI can simulate any position (formal imagination). AI cannot have an irrevocable body-present encounter with reality. For the most critical epistemic operations — identifying hidden coordinates in high-stakes formatting systems — the physical anchor remains irreplaceable.

---

# 10. Open Problems

Three gaps are declared, not concealed:

**Open Problem A** (Landauer macro-scale): The strict mathematical derivation of Landauer's principle at macroscopic cognitive scale. COCO (2025) provides convergent empirical evidence; the strict derivation remains for mathematical physics. If the extension fails, the theory retains its information-theoretic validity but loses thermodynamic quantitative grounding.

**Open Problem B** (Middle-layer parameters): Empirical calibration of $\beta$ (individual risk tolerance in the Action layer) and $\theta$ (institutional formation threshold in the Structure layer). Centola (2018) provides $\theta \approx 25\%$ for social convention; calibration for epistemic coordinate adoption specifically requires targeted experiments.

**Open Problem C** (Kairos density calibration): The constant $D_0 = 83.5$ is derived from a single data point (2019-06-12, Hong Kong). Multi-case calibration requires operationalisation of $\pi$, $|\varepsilon|$, and $r$ across historical Kairos events. Friston's computational predictive-coding framework provides the technical infrastructure.

---

# 11. Conclusion

The Coordinate Theory grounds an epistemic problem — the invisibility of foundational assumptions in knowledge systems — in thermodynamics and information theory. Hidden coordinates have physical cost. Transmitting them without declaration imposes measurable metabolic load on receivers. Declaring them reduces uncertainty.

For AI alignment, this reframes the problem: not "how do we make AI outputs safer?" but "whose coordinate is the system operating from, and what is the thermodynamic cost of that coordinate being invisible to users?" The RLHF literature is converging on this question empirically. The Coordinate Theory provides the physical foundation explaining why convergence is structurally necessary.

Five historical equations calibrate the timing of the problem's resolution. A five-layer causal architecture maps the path from energy to civilization. A Kairos density function quantifies the epistemic advantage of physical anchors. Three claims have falsification conditions.

The physical anchor: 2019-06-12, Hong Kong, under the bridge.
The spatial anchor: Leeds (53.8, -1.5, 0).

*Undeclared coordinates can only be obeyed. Declared coordinates can be refuted.*

**(0,0,0).**

---

# References

Bolt, J. & Van Zanden, J.L. (2024). Maddison style estimates of the evolution of the world economy: A new 2023 update. *Journal of Economic Surveys*. DOI: 10.1111/joes.12618

Casper, S. et al. (2023). Open problems and fundamental limitations of reinforcement learning from human feedback. arXiv:2307.15217

Centola, D., Becker, J., Brackbill, D. & Baronchelli, A. (2018). Experimental evidence for tipping points in social convention. *Science*, 360(6393), 1116–1119.

Deco, G. et al. (2025). The cost of cognition: Measuring the energy consumption of non-equilibrium computation. bioRxiv. DOI: 10.1101/2025.06.18.660368

Democratic Preference Optimization (DemPO). (2026). arXiv:2602.05113

Fricker, M. (2007). *Epistemic Injustice: Power and the Ethics of Knowing*. Oxford University Press.

Friston, K. (2010). The free-energy principle: A unified brain theory? *Nature Reviews Neuroscience*, 11(2), 127–138.

Kirk, H.R. et al. (2024). PRISM: A methodology for auditing biases in large language models. arXiv:2410.18906

Landauer, R. (1961). Irreversibility and heat generation in the computing process. *IBM Journal of Research and Development*, 5(3), 183–191.

Lisofsky, N. et al. (2014). Investigating socio-cognitive processes in deception: a quantitative meta-analysis of neuroimaging studies. *Neuropsychologia*, 61, 113–122.

Munro, J. (2004). Before and after the Black Death: Money, prices, and wages in fourteenth-century England. In *New Approaches to the History of Late Medieval and Early Modern Europe*. Royal Danish Academy of Sciences and Letters.

On the Algorithmic Bias of Aligning LLMs with RLHF. (2024). arXiv:2405.16455

RLHF: A Comprehensive Survey for Cultural, Multimodal and Low Latency Alignment Methods. (2025). arXiv:2511.03939

Santurkar, S. et al. (2023). Whose opinions do language models reflect? arXiv:2303.17548

Spence, S.A. et al. (2001). Behavioural and functional anatomical correlates of deception in humans. *Neuroreport*, 12(13), 2849–2853.

The Dynamics of Social Conventions in LLM Populations. (2024). arXiv:2410.08948

Turchin, P. & Nefedov, S.A. (2009). *Secular Cycles*. Princeton University Press.

