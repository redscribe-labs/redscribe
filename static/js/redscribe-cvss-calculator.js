(function () {
  const METRICS_V3_1 = {
    AV: {
      name: "Attack Vector",
      values: {
        N: "Network",
        A: "Adjacent Network",
        L: "Local",
        P: "Physical",
      },
      weights: { N: 0.85, A: 0.62, L: 0.55, P: 0.2 },
    },
    AC: {
      name: "Attack Complexity",
      values: {
        L: "Low",
        H: "High",
      },
      weights: { L: 0.77, H: 0.44 },
    },
    PR: {
      name: "Privileges Required",
      values: {
        N: "None",
        L: "Low",
        H: "High",
      },
      weightsUnchanged: { N: 0.85, L: 0.62, H: 0.27 },
      weightsChanged: { N: 0.85, L: 0.68, H: 0.5 },
    },
    UI: {
      name: "User Interaction",
      values: {
        N: "None",
        R: "Required",
      },
      weights: { N: 0.85, R: 0.62 },
    },
    S: {
      name: "Scope",
      values: {
        U: "Unchanged",
        C: "Changed",
      },
    },
    C: {
      name: "Confidentiality",
      values: {
        H: "High",
        L: "Low",
        N: "None",
      },
      weights: { H: 0.56, L: 0.22, N: 0 },
    },
    I: {
      name: "Integrity",
      values: {
        H: "High",
        L: "Low",
        N: "None",
      },
      weights: { H: 0.56, L: 0.22, N: 0 },
    },
    A: {
      name: "Availability",
      values: {
        H: "High",
        L: "Low",
        N: "None",
      },
      weights: { H: 0.56, L: 0.22, N: 0 },
    },
  };

  const METRICS_V4_0 = {
    AV: {
      name: "Attack Vector",
      values: {
        N: "Network",
        A: "Adjacent",
        L: "Local",
        P: "Physical",
      },
    },
    AC: {
      name: "Attack Complexity",
      values: {
        L: "Low",
        H: "High",
      },
    },
    AT: {
      name: "Attack Requirements",
      values: {
        N: "None",
        P: "Present",
      },
    },
    PR: {
      name: "Privileges Required",
      values: {
        N: "None",
        L: "Low",
        H: "High",
      },
    },
    UI: {
      name: "User Interaction",
      values: {
        N: "None",
        P: "Passive",
        A: "Active",
      },
    },
    VC: {
      name: "Confidentiality (Vulnerable System)",
      values: {
        H: "High",
        L: "Low",
        N: "None",
      },
    },
    VI: {
      name: "Integrity (Vulnerable System)",
      values: {
        H: "High",
        L: "Low",
        N: "None",
      },
    },
    VA: {
      name: "Availability (Vulnerable System)",
      values: {
        H: "High",
        L: "Low",
        N: "None",
      },
    },
    SC: {
      name: "Confidentiality (Subsequent System)",
      values: {
        H: "High",
        L: "Low",
        N: "None",
      },
    },
    SI: {
      name: "Integrity (Subsequent System)",
      values: {
        H: "High",
        L: "Low",
        N: "None",
      },
    },
    SA: {
      name: "Availability (Subsequent System)",
      values: {
        H: "High",
        L: "Low",
        N: "None",
      },
    },
  };

  const METRIC_ORDER_V3_1 = ["AV", "AC", "PR", "UI", "S", "C", "I", "A"];
  const METRIC_ORDER_V4_0 = ["AV", "AC", "AT", "PR", "UI", "VC", "VI", "VA", "SC", "SI", "SA"];

  function roundup(input) {
    const intInput = Math.round(input * 100000);
    if (intInput % 10000 === 0) {
      return intInput / 100000;
    }
    return (Math.floor(intInput / 10000) + 1) / 10;
  }

  function computeScoreV3_1(values) {
    for (const metric of METRIC_ORDER_V3_1) {
      if (!values[metric]) {
        return { score: null, vector: null };
      }
    }

    const av = METRICS_V3_1.AV.weights[values.AV];
    const ac = METRICS_V3_1.AC.weights[values.AC];
    const scope = values.S;
    const prWeights =
      scope === "U"
        ? METRICS_V3_1.PR.weightsUnchanged
        : METRICS_V3_1.PR.weightsChanged;
    const pr = prWeights[values.PR];
    const ui = METRICS_V3_1.UI.weights[values.UI];
    const c = METRICS_V3_1.C.weights[values.C];
    const i = METRICS_V3_1.I.weights[values.I];
    const a = METRICS_V3_1.A.weights[values.A];

    const iss = 1 - (1 - c) * (1 - i) * (1 - a);
    const exploitability = 8.22 * av * ac * pr * ui;

    let impact;
    if (scope === "U") {
      impact = 6.42 * iss;
    } else {
      impact = 7.52 * (iss - 0.029) - 3.25 * Math.pow(iss - 0.02, 15);
    }

    let baseScore;
    if (impact <= 0) {
      baseScore = 0.0;
    } else if (scope === "U") {
      baseScore = roundup(Math.min(impact + exploitability, 10));
    } else {
      baseScore = roundup(Math.min(1.08 * (impact + exploitability), 10));
    }

    const vector = `CVSS:3.1/AV:${values.AV}/AC:${values.AC}/PR:${values.PR}/UI:${values.UI}/S:${values.S}/C:${values.C}/I:${values.I}/A:${values.A}`;

    return {
      score: baseScore.toFixed(1),
      vector,
    };
  }

  function computeScoreV4_0(values) {
    for (const metric of METRIC_ORDER_V4_0) {
      if (!values[metric]) {
        return { score: null, vector: null };
      }
    }

    const vectorStr = `CVSS:4.0/AV:${values.AV}/AC:${values.AC}/AT:${values.AT}/PR:${values.PR}/UI:${values.UI}/VC:${values.VC}/VI:${values.VI}/VA:${values.VA}/SC:${values.SC}/SI:${values.SI}/SA:${values.SA}`;

    try {
      const c = new window.CVSS40(vectorStr);
      return {
        score: c.score.toFixed(1),
        vector: c.vector.raw,
      };
    } catch (e) {
      return { score: null, vector: null };
    }
  }

  function parseVectorV3_1(vectorStr) {
    if (!vectorStr) return null;

    vectorStr = vectorStr.trim();
    if (!vectorStr.startsWith("CVSS:3.1/")) return null;

    const parts = vectorStr.split("/");
    if (parts.length < 9) return null;

    const values = {};
    for (let i = 1; i <= 8; i++) {
      const token = parts[i];
      if (!token || !token.includes(":")) return null;

      const [metric, value] = token.split(":", 1);
      const actualValue = token.substring(metric.length + 1);

      if (!METRIC_ORDER_V3_1.includes(metric)) return null;
      if (!METRICS_V3_1[metric].values[actualValue]) return null;

      values[metric] = actualValue;
    }

    return values;
  }

  function parseVectorV4_0(vectorStr) {
    if (!vectorStr) return null;

    vectorStr = vectorStr.trim();
    if (!vectorStr.startsWith("CVSS:4.0/")) return null;

    const parts = vectorStr.split("/");
    if (parts.length < 12) return null;

    const values = {};
    for (let i = 1; i <= 11; i++) {
      const token = parts[i];
      if (!token || !token.includes(":")) return null;

      const [metric, value] = token.split(":", 1);
      const actualValue = token.substring(metric.length + 1);

      if (!METRIC_ORDER_V4_0.includes(metric)) return null;
      if (!METRICS_V4_0[metric].values[actualValue]) return null;

      values[metric] = actualValue;
    }

    return values;
  }

  function severityFromScore(score) {
    const n = parseFloat(score);
    if (isNaN(n)) return null;
    if (n <= 0) return "INFORMATIONAL";
    if (n < 4.0) return "LOW";
    if (n < 7.0) return "MEDIUM";
    if (n < 9.0) return "HIGH";
    return "CRITICAL";
  }

  function setupCalculator() {
    const scoreInput = document.getElementById("id_cvss_score") || document.getElementById("id_default_cvss_score");
    const vectorInput = document.getElementById("id_cvss_vector") || document.getElementById("id_default_cvss_vector");

    if (!scoreInput || !vectorInput) {
      return;
    }

    const severitySelect =
      document.getElementById("id_severity") || document.getElementById("id_default_severity");

    function applySeverity(score) {
      if (!severitySelect) return;
      const severity = severityFromScore(score);
      if (severity && [...severitySelect.options].some((o) => o.value === severity)) {
        severitySelect.value = severity;
      }
    }

    scoreInput.addEventListener("input", function () {
      applySeverity(scoreInput.value);
    });

    const calculatorContainer = document.createElement("div");
    calculatorContainer.className = "card space-y-4 mb-4";

    const titleDiv = document.createElement("div");
    titleDiv.className = "flex items-center justify-between";

    const titleSpan = document.createElement("h3");
    titleSpan.className = "font-semibold text-slate-900";
    titleSpan.textContent = "CVSS Calculator";
    titleDiv.appendChild(titleSpan);

    const toggleDiv = document.createElement("div");
    toggleDiv.className = "flex gap-2";

    const btn31 = document.createElement("button");
    btn31.type = "button";
    btn31.className = "btn-primary px-3 py-1 text-sm";
    btn31.textContent = "v3.1";
    btn31.setAttribute("data-version", "3.1");
    btn31.setAttribute("aria-pressed", "true");

    const btn40 = document.createElement("button");
    btn40.type = "button";
    btn40.className = "btn-secondary px-3 py-1 text-sm";
    btn40.textContent = "v4.0";
    btn40.setAttribute("data-version", "4.0");
    btn40.setAttribute("aria-pressed", "false");

    toggleDiv.setAttribute("role", "group");
    toggleDiv.setAttribute("aria-label", "CVSS version");
    toggleDiv.appendChild(btn31);
    toggleDiv.appendChild(btn40);
    titleDiv.appendChild(toggleDiv);
    calculatorContainer.appendChild(titleDiv);

    const gridDiv31 = document.createElement("div");
    gridDiv31.className = "grid grid-cols-2 gap-3";
    gridDiv31.setAttribute("data-grid", "3.1");
    calculatorContainer.appendChild(gridDiv31);

    const gridDiv40 = document.createElement("div");
    gridDiv40.className = "grid grid-cols-2 gap-3 hidden";
    gridDiv40.setAttribute("data-grid", "4.0");
    calculatorContainer.appendChild(gridDiv40);

    const selects31 = {};
    const selects40 = {};

    for (const metric of METRIC_ORDER_V3_1) {
      const metricDef = METRICS_V3_1[metric];

      const selectDiv = document.createElement("div");
      selectDiv.className = "flex flex-col";

      const label = document.createElement("label");
      label.className = "field-label";
      label.textContent = metricDef.name;
      label.htmlFor = `cvss-3-1-${metric}`;
      selectDiv.appendChild(label);

      const select = document.createElement("select");
      select.id = `cvss-3-1-${metric}`;
      select.className = "field-input";
      select.setAttribute("data-cvss-metric", metric);
      select.setAttribute("data-cvss-version", "3.1");

      const emptyOption = document.createElement("option");
      emptyOption.value = "";
      emptyOption.textContent = "—";
      select.appendChild(emptyOption);

      for (const [code, label_text] of Object.entries(metricDef.values)) {
        const option = document.createElement("option");
        option.value = code;
        option.textContent = `${code} – ${label_text}`;
        select.appendChild(option);
      }

      select.addEventListener("change", updateScoreV3_1);
      selectDiv.appendChild(select);
      gridDiv31.appendChild(selectDiv);
      selects31[metric] = select;
    }

    for (const metric of METRIC_ORDER_V4_0) {
      const metricDef = METRICS_V4_0[metric];

      const selectDiv = document.createElement("div");
      selectDiv.className = "flex flex-col";

      const label = document.createElement("label");
      label.className = "field-label";
      label.textContent = metricDef.name;
      label.htmlFor = `cvss-4-0-${metric}`;
      selectDiv.appendChild(label);

      const select = document.createElement("select");
      select.id = `cvss-4-0-${metric}`;
      select.className = "field-input";
      select.setAttribute("data-cvss-metric", metric);
      select.setAttribute("data-cvss-version", "4.0");

      const emptyOption = document.createElement("option");
      emptyOption.value = "";
      emptyOption.textContent = "—";
      select.appendChild(emptyOption);

      for (const [code, label_text] of Object.entries(metricDef.values)) {
        const option = document.createElement("option");
        option.value = code;
        option.textContent = `${code} – ${label_text}`;
        select.appendChild(option);
      }

      select.addEventListener("change", updateScoreV4_0);
      selectDiv.appendChild(select);
      gridDiv40.appendChild(selectDiv);
      selects40[metric] = select;
    }

    const hintDiv = document.createElement("p");
    hintDiv.className = "field-help text-xs";
    hintDiv.textContent =
      "Auto-fills from the calculator above, or enter/paste a vector manually.";
    calculatorContainer.appendChild(hintDiv);

    const scoreFieldDiv = scoreInput.closest("div");
    scoreFieldDiv.parentElement.insertBefore(calculatorContainer, scoreFieldDiv);

    const vectorFieldDiv = vectorInput.closest("div");
    const existingHelp = vectorFieldDiv.querySelector(".field-help");
    if (!existingHelp) {
      const newHint = document.createElement("p");
      newHint.className = "field-help";
      newHint.textContent =
        "Auto-fills from the calculator above, or enter/paste a vector manually.";
      vectorFieldDiv.appendChild(newHint);
    }

    btn31.addEventListener("click", function (e) {
      e.preventDefault();
      gridDiv31.classList.remove("hidden");
      gridDiv40.classList.add("hidden");
      btn31.classList.remove("btn-secondary");
      btn31.classList.add("btn-primary");
      btn40.classList.remove("btn-primary");
      btn40.classList.add("btn-secondary");
      btn31.setAttribute("aria-pressed", "true");
      btn40.setAttribute("aria-pressed", "false");
    });

    btn40.addEventListener("click", function (e) {
      e.preventDefault();
      gridDiv31.classList.add("hidden");
      gridDiv40.classList.remove("hidden");
      btn40.classList.remove("btn-secondary");
      btn40.classList.add("btn-primary");
      btn31.classList.remove("btn-primary");
      btn31.classList.add("btn-secondary");
      btn40.setAttribute("aria-pressed", "true");
      btn31.setAttribute("aria-pressed", "false");
    });

    function updateScoreV3_1() {
      const values = {};
      for (const metric of METRIC_ORDER_V3_1) {
        values[metric] = selects31[metric].value || null;
      }

      const result = computeScoreV3_1(values);
      if (result.score !== null) {
        scoreInput.value = result.score;
        vectorInput.value = result.vector;
        applySeverity(result.score);
      }
    }

    function updateScoreV4_0() {
      const values = {};
      for (const metric of METRIC_ORDER_V4_0) {
        values[metric] = selects40[metric].value || null;
      }

      const result = computeScoreV4_0(values);
      if (result.score !== null) {
        scoreInput.value = result.score;
        vectorInput.value = result.vector;
        applySeverity(result.score);
      }
    }

    if (vectorInput.value) {
      const parsedV3_1 = parseVectorV3_1(vectorInput.value);
      if (parsedV3_1) {
        for (const metric of METRIC_ORDER_V3_1) {
          if (parsedV3_1[metric]) {
            selects31[metric].value = parsedV3_1[metric];
          }
        }
        return;
      }

      const parsedV4_0 = parseVectorV4_0(vectorInput.value);
      if (parsedV4_0) {
        for (const metric of METRIC_ORDER_V4_0) {
          if (parsedV4_0[metric]) {
            selects40[metric].value = parsedV4_0[metric];
          }
        }
        gridDiv31.classList.add("hidden");
        gridDiv40.classList.remove("hidden");
        btn40.classList.remove("btn-secondary");
        btn40.classList.add("btn-primary");
        btn31.classList.remove("btn-primary");
        btn31.classList.add("btn-secondary");
        btn40.setAttribute("aria-pressed", "true");
        btn31.setAttribute("aria-pressed", "false");
      }
    }
  }

  document.addEventListener("DOMContentLoaded", setupCalculator);
})();
