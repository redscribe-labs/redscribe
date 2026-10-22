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

  // Section layout for the calculator, after FIRST's own calculators. Labels
  // here are the short in-section names; METRICS_* keep the full names.
  const GROUPS_V3_1 = [
    { title: "Exploitability", metrics: [["AV", "Attack Vector"], ["AC", "Attack Complexity"], ["PR", "Privileges Required"], ["UI", "User Interaction"]] },
    { title: "Scope", metrics: [["S", "Scope"]] },
    { title: "Impact", metrics: [["C", "Confidentiality"], ["I", "Integrity"], ["A", "Availability"]] },
  ];
  const GROUPS_V4_0 = [
    { title: "Exploitability", metrics: [["AV", "Attack Vector"], ["AC", "Attack Complexity"], ["AT", "Attack Requirements"], ["PR", "Privileges Required"], ["UI", "User Interaction"]] },
    { title: "Vulnerable system impact", metrics: [["VC", "Confidentiality"], ["VI", "Integrity"], ["VA", "Availability"]] },
    { title: "Subsequent system impact", metrics: [["SC", "Confidentiality"], ["SI", "Integrity"], ["SA", "Availability"]] },
  ];

  // Hover help for each metric ("_") and value, condensed from the FIRST specs.
  const CIA_HELP = {
    H: "Total loss, or a serious loss with a direct, serious consequence.",
    L: "Some loss, but limited in scope or without a serious consequence.",
    N: "No loss.",
  };
  const HELP_V3_1 = {
    AV: {
      _: "The context in which exploitation is possible.",
      N: "Exploitable remotely across the network, e.g. over the internet.",
      A: "Limited to a logically adjacent network, e.g. the same subnet or Bluetooth.",
      L: "Needs local access or a local session, or relies on a user to open something.",
      P: "Needs physical access to the device.",
    },
    AC: {
      _: "Conditions outside the attacker's control that must exist for the attack to work.",
      L: "No special conditions; the attack works repeatably.",
      H: "Depends on conditions the attacker doesn't control, e.g. winning a race or a MITM position.",
    },
    PR: {
      _: "The privileges the attacker needs before exploiting.",
      N: "Unauthenticated.",
      L: "Basic user privileges.",
      H: "Significant (e.g. administrative) privileges.",
    },
    UI: {
      _: "Whether someone other than the attacker has to take part.",
      N: "No user interaction needed.",
      R: "A user must take some action, e.g. click a link.",
    },
    S: {
      _: "Whether impact reaches beyond the vulnerable component's security authority.",
      U: "Impact is limited to the vulnerable component.",
      C: "Impact reaches components beyond it, e.g. a VM escape or stored XSS hitting the browser.",
    },
    C: Object.assign({ _: "Impact on the confidentiality of information." }, CIA_HELP),
    I: Object.assign({ _: "Impact on the integrity (trustworthiness) of information." }, CIA_HELP),
    A: Object.assign({ _: "Impact on the availability of the component." }, CIA_HELP),
  };
  const HELP_V4_0 = {
    AV: HELP_V3_1.AV,
    AC: {
      _: "Security-enhancing conditions the attacker must evade or overcome.",
      L: "No target-specific evasion or reconnaissance needed.",
      H: "Must evade or circumvent active protections (e.g. ASLR, DEP) or obtain target-specific secrets.",
    },
    AT: {
      _: "Deployment or execution conditions on the target that the attack depends on.",
      N: "Works against all or most instances of the vulnerable system.",
      P: "Depends on specific conditions, e.g. a race condition or a network injection position.",
    },
    PR: HELP_V3_1.PR,
    UI: {
      _: "Whether a human user other than the attacker has to take part.",
      N: "No user interaction needed.",
      P: "Limited, involuntary interaction, e.g. visiting a crafted page.",
      A: "Specific, conscious actions, e.g. importing a file or dismissing a warning.",
    },
    VC: Object.assign({ _: "Confidentiality impact on the vulnerable system." }, CIA_HELP),
    VI: Object.assign({ _: "Integrity impact on the vulnerable system." }, CIA_HELP),
    VA: Object.assign({ _: "Availability impact on the vulnerable system." }, CIA_HELP),
    SC: Object.assign({ _: "Confidentiality impact on systems beyond the vulnerable one." }, CIA_HELP),
    SI: Object.assign({ _: "Integrity impact on systems beyond the vulnerable one." }, CIA_HELP),
    SA: Object.assign({ _: "Availability impact on systems beyond the vulnerable one." }, CIA_HELP),
  };

  // Same colours as the app's severity badges (badge_class in redscribe_extras).
  const SEVERITY_BADGES = {
    CRITICAL: "badge-red", HIGH: "badge-orange", MEDIUM: "badge-amber", LOW: "badge-mist", INFORMATIONAL: "badge-slate",
  };

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
        if (severitySelect.value !== severity) {
          severitySelect.value = severity;
          severitySelect.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
    }

    scoreInput.addEventListener("input", function () {
      applySeverity(scoreInput.value);
    });

    function el(tag, className, text) {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }

    // The calculator lives in a modal appended to <body>, outside the form, so
    // picking metrics doesn't touch the form until "Apply" writes the result.
    const modal = el("dialog", "p-0 border-0 bg-transparent w-[calc(100%-2rem)] max-w-3xl backdrop:bg-black/40");
    modal.id = "cvss-calculator-modal";
    modal.setAttribute("aria-labelledby", "cvss-calculator-title");
    modal.style.position = "fixed";
    modal.style.top = "50%";
    modal.style.left = "50%";
    modal.style.transform = "translate(-50%, -50%)";
    modal.style.margin = "0";

    // Header (title, version, live score) and footer (actions) stay put; only
    // the metric list between them scrolls.
    const panel = el("div", "card !m-0 !p-0 flex flex-col max-h-[calc(100vh-2rem)] overflow-hidden");
    modal.appendChild(panel);

    const header = el("div", "px-5 pt-5 pb-4 border-b border-slate-200 space-y-4");
    panel.appendChild(header);

    const titleRow = el("div", "flex items-center justify-between gap-3");
    const title = el("h2", "text-lg font-semibold text-slate-900", "CVSS Calculator");
    title.id = "cvss-calculator-title";
    titleRow.appendChild(title);

    const toggle = el("div", "inline-flex rounded-md border border-slate-300 p-0.5 bg-slate-50");
    toggle.setAttribute("role", "group");
    toggle.setAttribute("aria-label", "CVSS version");
    const versionButtons = {};
    for (const v of ["3.1", "4.0"]) {
      const btn = el("button", "rounded px-3 py-1 text-sm font-medium transition-colors", `v${v}`);
      btn.type = "button";
      btn.setAttribute("data-version", v);
      btn.addEventListener("click", function () { showVersion(v); });
      toggle.appendChild(btn);
      versionButtons[v] = btn;
    }
    titleRow.appendChild(toggle);
    header.appendChild(titleRow);

    const scoreRow = el("div", "flex items-center gap-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3");
    const scoreValue = el("div", "font-mono text-3xl font-semibold tabular-nums text-slate-900 w-16 shrink-0 text-center");
    scoreValue.setAttribute("aria-live", "polite");
    const scoreMeta = el("div", "min-w-0 space-y-1");
    const scoreSeverity = el("div", "flex items-center gap-2 text-sm text-slate-600");
    const scoreVector = el("p", "font-mono text-xs text-slate-500 break-all");
    scoreMeta.appendChild(scoreSeverity);
    scoreMeta.appendChild(scoreVector);
    scoreRow.appendChild(scoreValue);
    scoreRow.appendChild(scoreMeta);
    header.appendChild(scoreRow);

    const body = el("div", "overflow-y-auto px-5 py-4");
    panel.appendChild(body);

    const footer = el("div", "flex items-center gap-2 px-5 py-4 border-t border-slate-200");
    const applyBtn = el("button", "btn-primary", "Apply");
    applyBtn.type = "button";
    const cancelBtn = el("button", "btn-secondary", "Cancel");
    cancelBtn.type = "button";
    const clearBtn = el("button", "ml-auto text-sm text-slate-500 hover:text-slate-700 hover:underline", "Clear all");
    clearBtn.type = "button";
    footer.appendChild(applyBtn);
    footer.appendChild(cancelBtn);
    footer.appendChild(clearBtn);
    panel.appendChild(footer);

    // One section per metric group; each metric is a radio group drawn as a
    // row of toggle buttons (native radios, so arrow keys and forms behave).
    function buildVersion(version, groups, metrics, help) {
      const container = el("div", "space-y-5");
      const radios = {};
      const idPrefix = `cvss-${version.replace(".", "-")}`;
      for (const group of groups) {
        const section = el("section", "space-y-3");
        section.appendChild(el("h3", "text-xs font-semibold uppercase tracking-wide text-slate-500", group.title));
        for (const [metric, label] of group.metrics) {
          const fieldset = el("fieldset", "sm:grid sm:grid-cols-[11rem_1fr] sm:items-center gap-x-4");
          const legend = el("legend", "contents");
          const legendText = el("span", "block text-sm font-medium text-slate-700 mb-1.5 sm:mb-0 cursor-help", `${label} (${metric})`);
          legendText.title = help[metric]._;
          legend.appendChild(legendText);
          fieldset.appendChild(legend);

          const options = el("div", "flex flex-wrap gap-1.5");
          radios[metric] = {};
          for (const [code, valueLabel] of Object.entries(metrics[metric].values)) {
            const id = `${idPrefix}-${metric}-${code}`;
            const wrap = el("span", "relative");
            const input = el("input", "peer sr-only");
            input.type = "radio";
            input.name = `${idPrefix}-${metric}`;
            input.id = id;
            input.value = code;
            input.addEventListener("change", updatePreview);
            const optionLabel = el(
              "label",
              "inline-flex cursor-pointer select-none items-center gap-1 rounded-md border border-slate-300 bg-white dark:bg-slate-100 " +
              "px-3 py-1.5 text-sm text-slate-700 shadow-sm transition-colors hover:bg-slate-50 " +
              "peer-checked:border-brand-600 peer-checked:bg-brand-600 peer-checked:text-white peer-checked:hover:bg-brand-700 " +
              "peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500 peer-focus-visible:ring-offset-1"
            );
            optionLabel.htmlFor = id;
            optionLabel.title = help[metric][code] || "";
            optionLabel.appendChild(document.createTextNode(valueLabel));
            optionLabel.appendChild(el("span", "font-mono text-xs opacity-70", `(${code})`));
            wrap.appendChild(input);
            wrap.appendChild(optionLabel);
            options.appendChild(wrap);
            radios[metric][code] = input;
          }
          fieldset.appendChild(options);
          section.appendChild(fieldset);
        }
        container.appendChild(section);
      }
      body.appendChild(container);
      return { container, radios };
    }

    const calc = {
      "3.1": Object.assign(buildVersion("3.1", GROUPS_V3_1, METRICS_V3_1, HELP_V3_1), { order: METRIC_ORDER_V3_1, compute: computeScoreV3_1, parse: parseVectorV3_1 }),
      "4.0": Object.assign(buildVersion("4.0", GROUPS_V4_0, METRICS_V4_0, HELP_V4_0), { order: METRIC_ORDER_V4_0, compute: computeScoreV4_0, parse: parseVectorV4_0 }),
    };

    document.body.appendChild(modal);

    const openBtn = el("button", "btn-secondary w-full text-sm", "Open CVSS calculator");
    openBtn.type = "button";

    const scoreFieldDiv = scoreInput.closest("div");
    scoreFieldDiv.parentElement.insertBefore(openBtn, scoreFieldDiv);

    const vectorFieldDiv = vectorInput.closest("div");
    const existingHelp = vectorFieldDiv.querySelector(".field-help");
    if (!existingHelp) {
      const newHint = el("p", "field-help", "Set it with the CVSS calculator, or enter/paste a vector manually.");
      vectorFieldDiv.appendChild(newHint);
    }

    let version = "3.1";

    function showVersion(v) {
      version = v;
      for (const [key, c] of Object.entries(calc)) {
        const active = key === v;
        c.container.classList.toggle("hidden", !active);
        const btn = versionButtons[key];
        btn.setAttribute("aria-pressed", String(active));
        btn.classList.toggle("bg-brand-600", active);
        btn.classList.toggle("text-white", active);
        btn.classList.toggle("shadow-sm", active);
        btn.classList.toggle("text-slate-600", !active);
        btn.classList.toggle("hover:text-slate-900", !active);
      }
      updatePreview();
    }

    function selectedValues(c) {
      const values = {};
      for (const metric of c.order) {
        const checked = Object.values(c.radios[metric]).find((r) => r.checked);
        values[metric] = checked ? checked.value : null;
      }
      return values;
    }

    function currentResult() {
      const c = calc[version];
      return c.compute(selectedValues(c));
    }

    function updatePreview() {
      const c = calc[version];
      const values = selectedValues(c);
      const result = c.compute(values);
      scoreSeverity.replaceChildren();
      if (result.score === null) {
        const set = c.order.filter((m) => values[m]).length;
        scoreValue.textContent = "—";
        scoreSeverity.textContent = `${set} of ${c.order.length} metrics set`;
        scoreVector.textContent = "Pick a value for every metric to get a score.";
        applyBtn.disabled = true;
        return;
      }
      const severity = severityFromScore(result.score);
      scoreValue.textContent = result.score;
      if (severity) {
        scoreSeverity.appendChild(el("span", SEVERITY_BADGES[severity], severity === "INFORMATIONAL" ? "None" : severity));
      }
      scoreVector.textContent = result.vector;
      applyBtn.disabled = false;
    }

    function clearAll() {
      for (const c of Object.values(calc)) {
        for (const group of Object.values(c.radios)) {
          for (const radio of Object.values(group)) radio.checked = false;
        }
      }
    }

    clearBtn.addEventListener("click", function () {
      for (const group of Object.values(calc[version].radios)) {
        for (const radio of Object.values(group)) radio.checked = false;
      }
      updatePreview();
    });

    // Sync the calculator to whatever is in the vector field right now, since
    // it may have been pasted or edited by hand since the modal last closed.
    function loadFromVector() {
      clearAll();
      for (const [key, c] of Object.entries(calc)) {
        const parsed = c.parse(vectorInput.value);
        if (parsed) {
          for (const metric of c.order) {
            if (parsed[metric]) c.radios[metric][parsed[metric]].checked = true;
          }
          showVersion(key);
          return;
        }
      }
      showVersion(version);
    }

    openBtn.addEventListener("click", function () {
      loadFromVector();
      modal.showModal();
      const c = calc[version];
      const first = c.radios[c.order[0]];
      (Object.values(first).find((r) => r.checked) || Object.values(first)[0]).focus();
    });

    applyBtn.addEventListener("click", function () {
      const result = currentResult();
      if (result.score === null) return;
      scoreInput.value = result.score;
      vectorInput.value = result.vector;
      // Fire input events so autosave and validation see the change; the
      // score listener above also syncs the severity.
      scoreInput.dispatchEvent(new Event("input", { bubbles: true }));
      vectorInput.dispatchEvent(new Event("input", { bubbles: true }));
      modal.close();
      openBtn.focus();
    });

    cancelBtn.addEventListener("click", function () { modal.close(); });
    modal.addEventListener("click", function (e) {
      if (e.target === modal) modal.close();
    });
  }

  document.addEventListener("DOMContentLoaded", setupCalculator);
})();
