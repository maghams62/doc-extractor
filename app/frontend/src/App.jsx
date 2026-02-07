import React, { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const toTitle = (value) =>
  value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

const flattenObject = (obj, prefix = "") => {
  const rows = [];
  Object.entries(obj || {}).forEach(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      rows.push(...flattenObject(value, path));
    } else {
      rows.push({ path, value });
    }
  });
  return rows;
};

const getAtPath = (obj, path) => {
  return path.split(".").reduce((acc, key) => (acc ? acc[key] : undefined), obj);
};

const setAtPath = (obj, path, value) => {
  const parts = path.split(".");
  const next = { ...obj };
  let cursor = next;
  parts.forEach((part, idx) => {
    if (idx === parts.length - 1) {
      cursor[part] = value;
    } else {
      cursor[part] = { ...cursor[part] };
      cursor = cursor[part];
    }
  });
  return next;
};

const DEFAULT_REGISTRY = { fields: [], order: [] };

export default function App() {
  const [passportFile, setPassportFile] = useState(null);
  const [g28File, setG28File] = useState(null);
  const [result, setResult] = useState(null);
  const [runId, setRunId] = useState(null);
  const [status, setStatus] = useState("idle");
  const [autofillStatus, setAutofillStatus] = useState(null);
  const [validationReport, setValidationReport] = useState(null);
  const [validationError, setValidationError] = useState(null);
  const [validationAcknowledged, setValidationAcknowledged] = useState(false);
  const [validationFilter, setValidationFilter] = useState("human");
  const [languageInfo, setLanguageInfo] = useState(null);
  const [languageStatus, setLanguageStatus] = useState("idle");
  const [languageError, setLanguageError] = useState(null);
  const [translationStatus, setTranslationStatus] = useState("idle");
  const [translatedText, setTranslatedText] = useState("");
  const [translationRunId, setTranslationRunId] = useState(null);
  const [translationArtifacts, setTranslationArtifacts] = useState(null);
  const [translationError, setTranslationError] = useState(null);
  const [textActive, setTextActive] = useState("raw");
  const [activeStatus, setActiveStatus] = useState("idle");
  const [activeError, setActiveError] = useState(null);
  const [ocrLangOverride, setOcrLangOverride] = useState("auto");
  const [hasTranslation, setHasTranslation] = useState(false);
  const [translationWarning, setTranslationWarning] = useState(null);
  const [pipeline, setPipeline] = useState({
    review: "idle",
    extract: "idle",
    autofill: "idle",
    validate: "idle",
  });
  const [fieldRegistry, setFieldRegistry] = useState(DEFAULT_REGISTRY);
  const [reviewReport, setReviewReport] = useState(null);
  const [reviewSummary, setReviewSummary] = useState(null);
  const [reviewStatus, setReviewStatus] = useState("idle");
  const [reviewError, setReviewError] = useState(null);
  const [autoApproveStatus, setAutoApproveStatus] = useState("idle");
  const [reviewTab, setReviewTab] = useState("blocking");
  const [selectedField, setSelectedField] = useState(null);
  const [canonicalStatus, setCanonicalStatus] = useState("idle");
  const [canonicalSnapshot, setCanonicalSnapshot] = useState(null);
  const [missingDrafts, setMissingDrafts] = useState({});
  const [missingSaveState, setMissingSaveState] = useState("idle");
  const [missingSaveError, setMissingSaveError] = useState(null);
  const [missingDismissed, setMissingDismissed] = useState(false);
  const [dragState, setDragState] = useState({
    passport: false,
    g28: false,
  });
  const [editingFields, setEditingFields] = useState({});
  const [draftValues, setDraftValues] = useState({});
  const [saveState, setSaveState] = useState({});
  const translationFile = passportFile || g28File;
  const translationSource = passportFile ? "Passport" : g28File ? "G-28" : "";
  const translationDocType = passportFile ? "passport" : g28File ? "g28" : "";

  useEffect(() => {
    let cancelled = false;
    const loadRegistry = async () => {
      try {
        const response = await fetch(`${API_BASE}/field_registry`);
        if (!response.ok) return;
        const data = await response.json();
        if (cancelled || !data || !Array.isArray(data.fields)) return;
        const order = Array.isArray(data.order)
          ? data.order
          : data.fields.map((field) => field.key);
        setFieldRegistry({ fields: data.fields, order });
      } catch (error) {
        console.error("Field registry load failed", error);
      }
    };
    loadRegistry();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!translationFile) {
      setLanguageInfo(null);
      setLanguageStatus("idle");
      setLanguageError(null);
      setTranslationStatus("idle");
      setTranslatedText("");
      setTranslationRunId(null);
      setTranslationArtifacts(null);
      setTranslationError(null);
      setTextActive("raw");
      setActiveStatus("idle");
      setActiveError(null);
      setOcrLangOverride("auto");
      setHasTranslation(false);
      setTranslationWarning(null);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const detectLanguage = async () => {
      setLanguageStatus("detecting");
      setLanguageError(null);
      setLanguageInfo(null);
      setTranslationStatus("idle");
      setTranslatedText("");
      setTranslationRunId(null);
      setTranslationArtifacts(null);
      setTranslationError(null);
      setTextActive("raw");
      setActiveStatus("idle");
      setActiveError(null);
      setHasTranslation(false);
      setTranslationWarning(null);
      try {
        const formData = new FormData();
        formData.append("document", translationFile);
        if (translationDocType) {
          formData.append("doc_type", translationDocType);
        }
        if (ocrLangOverride && ocrLangOverride !== "auto") {
          formData.append("ocr_langs", ocrLangOverride);
        }
        const response = await fetch(`${API_BASE}/detect_language`, {
          method: "POST",
          body: formData,
          signal: controller.signal,
        });
        const data = await response.json();
        if (cancelled) return;
        if (!response.ok) {
          throw new Error(data?.error || "Language detection failed");
        }
        setLanguageInfo(data);
        setTextActive(data?.text_active || "raw");
        setHasTranslation(Boolean(data?.has_translation));
        setTranslationWarning(data?.translation_warning || null);
        setLanguageStatus("success");
      } catch (error) {
        if (cancelled) return;
        console.error("Language detection failed", error);
        setLanguageStatus("error");
        setLanguageError(error?.message || "Language detection failed");
      }
    };
    detectLanguage();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [translationFile, translationDocType, ocrLangOverride]);

  const autofillSummary =
    autofillStatus && typeof autofillStatus === "object" ? autofillStatus : null;
  const validationSummary =
    validationReport && typeof validationReport === "object" ? validationReport : null;
  const runFolder = useMemo(() => {
    if (!autofillSummary?.trace_path) return "";
    let folder = autofillSummary.trace_path.replace(/\\/g, "/");
    if (folder.endsWith("trace.zip")) {
      folder = folder.slice(0, -("trace.zip".length));
    }
    return folder.replace(/\/$/, "");
  }, [autofillSummary]);
  const runLogPath = runFolder ? `${runFolder}/run.log` : "";
  const showTranslationPanel = Boolean(translationFile || languageInfo || translationStatus !== "idle");
  const translatedTextPath =
    translationArtifacts?.translated_text || (translationRunId ? `runs/${translationRunId}/translated_text.txt` : "");
  const translatedOcrPath =
    translationArtifacts?.translated_ocr || (translationRunId ? `runs/${translationRunId}/translated_ocr.json` : "");

  const registryFields = fieldRegistry?.fields || [];
  const registryOrder = useMemo(() => {
    if (Array.isArray(fieldRegistry?.order) && fieldRegistry.order.length) {
      return fieldRegistry.order;
    }
    if (registryFields.length) {
      return registryFields.map((field) => field.key);
    }
    return [];
  }, [fieldRegistry, registryFields]);
  const fieldTypeMap = useMemo(() => {
    const map = {};
    registryFields.forEach((field) => {
      map[field.key] = field.type;
    });
    return map;
  }, [registryFields]);
  const fieldSpecMap = useMemo(() => {
    const map = {};
    registryFields.forEach((field) => {
      map[field.key] = field;
    });
    return map;
  }, [registryFields]);
  const passportFieldCount = useMemo(
    () => registryFields.filter((field) => field.key.startsWith("passport.")).length,
    [registryFields]
  );
  const g28FieldCount = useMemo(
    () => registryFields.filter((field) => field.key.startsWith("g28.")).length,
    [registryFields]
  );
  const fieldLabelMap = useMemo(() => {
    const map = {};
    registryFields.forEach((field) => {
      map[field.key] = field.label || toTitle(field.key.split(".").slice(-1)[0]);
    });
    return map;
  }, [registryFields]);

  const resolvedFields = useMemo(() => result?.meta?.resolved_fields || {}, [result]);

  const normalizeStatus = (value) => {
    if (!value) return "unknown";
    const lower = String(value).toLowerCase();
    if (lower === "amber") return "yellow";
    return lower;
  };

  const validateValue = (path, raw) => {
    const value = raw ? String(raw).trim() : "";
    if (!value) return { valid: false };
    const type = fieldTypeMap[path];
    if (!type) return { valid: true };
    if (type === "name") return { valid: value.length >= 2 };
    if (type === "email") return { valid: /^[^@]+@[^@]+\\.[^@]+$/.test(value) };
    if (type === "phone") return { valid: value.replace(/\\D/g, "").length >= 7 };
    if (type === "passport_number") return { valid: /^[A-Z0-9]{7,9}$/.test(value.toUpperCase()) };
    if (type === "sex") return { valid: ["M", "F", "X"].includes(value.toUpperCase()) };
    if (type === "zip") return /^\\d{5}(-\\d{4})?$/.test(value);
    if (type === "state") return value.length === 2;
    if (type === "date_past" || type === "date_future") {
      const parsed = Date.parse(value);
      if (Number.isNaN(parsed)) return { valid: false };
      const today = new Date();
      const dateVal = new Date(parsed);
      if (type === "date_past") return { valid: dateVal <= today };
      return { valid: dateVal >= today };
    }
    return { valid: true };
  };

  const normalizeValue = (value) => (value === null || value === undefined ? "" : String(value).trim());

  const isEmptyValue = (value) => normalizeValue(value) === "";

  const getActiveValue = (path, fallbackValue) => {
    const resolved = resolvedFields?.[path];
    if (resolved && Object.prototype.hasOwnProperty.call(resolved, "value")) {
      return resolved.value;
    }
    return fallbackValue;
  };

  const getSource = (path) => resolvedFields?.[path]?.source || result?.meta?.sources?.[path] || "";

  const getEvidence = (path) => result?.meta?.evidence?.[path] || "";

  const getSuggestionSourceLabel = (source) => {
    const normalized = String(source || "").toUpperCase();
    if (normalized === "LLM") return "LLM validator";
    if (normalized === "OCR") return "OCR alternate candidate";
    if (normalized === "MRZ") return "MRZ";
    if (normalized === "VALIDATOR") return "Derived";
    if (normalized === "MERGE") return "Merged";
    if (normalized === "HEURISTIC") return "Heuristic";
    return normalized || "Suggestion";
  };

  const formatValidatorVerdict = (value) => {
    if (!value) return { label: "Needs attention", tone: "yellow" };
    const normalized = String(value).toLowerCase();
    if (normalized === "verified" || normalized === "green") {
      return { label: "OK", tone: "green" };
    }
    if (normalized === "needs_review" || normalized === "amber" || normalized === "yellow") {
      return { label: "Needs attention", tone: "yellow" };
    }
    if (normalized === "missing_or_incorrect" || normalized === "red" || normalized === "fail") {
      return { label: "Missing/Invalid", tone: "red" };
    }
    return { label: "Needs attention", tone: "yellow" };
  };

  const formatIssueLabel = (value) => {
    const normalized = String(value || "").toUpperCase();
    if (!normalized) return "";
    if (["EMPTY_OPTIONAL", "EMPTY_OPTIONAL_PRESENT"].includes(normalized)) {
      return "";
    }
    const mapping = {
      HUMAN_REQUIRED: "Needs consent",
      AUTOFILL_FAILED: "Autofill failed",
      NOT_PRESENT_IN_DOC: "Missing in doc",
      EMPTY_REQUIRED: "Required missing",
      INVALID_FORMAT: "Invalid format",
      SUSPECT_LABEL_CAPTURE: "Label captured",
      CONFLICT: "Conflict",
      AUTOFILL_MISSED: "Autofill missed",
    };
    if (mapping[normalized]) return mapping[normalized];
    return normalized
      .toLowerCase()
      .split(/[_\s]+/)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  };

  const getRulesCheck = (path) => {
    const validationSource = validationSummary || reviewReport;
    const fieldValidation = validationSource?.fields?.[path];
    if (!fieldValidation) return null;
    const verdict =
      fieldValidation?.deterministic_validation?.verdict ||
      fieldValidation?.deterministic_verdict ||
      fieldValidation?.deterministic_validation?.status;
    return formatValidatorVerdict(verdict);
  };

  const getLlmCheck = (path) => {
    const validationSource = validationSummary || reviewReport;
    const fieldValidation = validationSource?.fields?.[path];
    if (!fieldValidation || !fieldValidation.llm_validation_invoked) return null;
    const verdict =
      fieldValidation?.llm_validation?.verdict ||
      fieldValidation?.llm_verdict ||
      fieldValidation?.llm_validation?.status;
    return formatValidatorVerdict(verdict);
  };

  const getSuggestions = (path, activeValue) => {
    const conflictEntry = reviewReport?.fields?.[path];
    const conflictCodes = conflictEntry?.deterministic_codes || [];
    const isConflict =
      Boolean(result?.meta?.conflicts?.[path]) ||
      conflictEntry?.issue_type === "CONFLICT" ||
      conflictCodes.includes("conflict_sources");
    if (isConflict) return [];
    const current = normalizeValue(activeValue).toLowerCase();
    const raw = result?.meta?.suggestions?.[path] || [];
    const conflict = Boolean(result?.meta?.conflicts?.[path]);
    const seen = new Set();
    return raw.filter((suggestion) => {
      if (!suggestion) return false;
      const value = normalizeValue(suggestion.value);
      const evidence = normalizeValue(suggestion.evidence);
      if (!value || !evidence) return false;
      if (value.toLowerCase() === current) return false;
      if (String(suggestion.source || "").toUpperCase() === "MERGE" && !conflict) return false;
      const key = `${value.toLowerCase()}|${evidence.toLowerCase()}|${suggestion.source || ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };

  const getEvidenceLevel = (evidence, statusLabel) => {
    if (!evidence) return { level: "low", label: "Low evidence" };
    if (statusLabel === "Verified") return { level: "high", label: "Evidence-backed" };
    return { level: "medium", label: "Needs review" };
  };

  const getStatusInfo = (path, activeValue, suggestions) => {
    const resolved = resolvedFields?.[path];
    const required = fieldSpecMap[path]?.required ?? false;
    const humanRequired = fieldSpecMap[path]?.human_required ?? false;
    const baseStatus = normalizeStatus(resolved?.status || statusMap[path] || "");
    const conflictEntry = reviewReport?.fields?.[path];
    const conflictCodes = conflictEntry?.deterministic_codes || [];
    const hasConflict =
      Boolean(result?.meta?.conflicts?.[path]) ||
      conflictEntry?.issue_type === "CONFLICT" ||
      conflictCodes.includes("conflict_sources");
    const requiresHuman = Boolean(resolved?.requires_human_input);
    const isLocked = Boolean(resolved?.locked);
    const empty = isEmptyValue(activeValue);

    if (empty) {
      if (humanRequired) {
        return { label: "Human required", tone: "yellow", bucket: "review" };
      }
      if (required) {
        return { label: "Missing input", tone: "red", bucket: "missing_required" };
      }
      return { label: "Verified", tone: "green", bucket: "optional_missing" };
    }
    if (baseStatus === "red") {
      return { label: "Incorrect", tone: "red", bucket: "incorrect" };
    }
    if (baseStatus === "yellow" || hasConflict || requiresHuman || (!isLocked && suggestions.length)) {
      return { label: "Needs review", tone: "yellow", bucket: "review" };
    }
    if (baseStatus === "green") {
      return { label: "Verified", tone: "green", bucket: "verified" };
    }
    return { label: "Needs review", tone: "yellow", bucket: "review" };
  };

  const getReason = (path, statusInfo, activeValue, suggestions) => {
    const resolved = resolvedFields?.[path];
    if (resolved?.reason) return resolved.reason;
    const fieldValidation = validationSummary?.fields?.[path];
    if (fieldValidation?.human_reason) return fieldValidation.human_reason;
    if (fieldValidation?.llm_reason) return fieldValidation.llm_reason;
    if (fieldValidation?.deterministic_reason) return fieldValidation.deterministic_reason;
    if (isEmptyValue(activeValue)) {
      const humanReason = fieldSpecMap[path]?.human_required_reason;
      if (humanReason) return humanReason;
      const required = fieldSpecMap[path]?.required ?? false;
      if (!required) return "Optional field left blank.";
      const presence = result?.meta?.presence?.[path];
      if (presence === "absent") {
        if (path.startsWith("passport.")) return "Passport not uploaded or unreadable.";
        if (path.startsWith("g28.")) return "G-28 not uploaded or unreadable.";
      }
      return "Could not read from document.";
    }
    if (statusInfo.bucket === "review" && suggestions.length) {
      return "Suggestion available.";
    }
    return "";
  };

  const tableRows = useMemo(() => {
    if (!result) return [];
    if (registryOrder.length) {
      return registryOrder.map((path) => ({
        path,
        value: getAtPath(result, path),
      }));
    }
    const rows = [];
    Object.keys(result)
      .filter((group) => group !== "meta")
      .forEach((group) => {
        const groupRows = flattenObject(result[group], group);
        rows.push(...groupRows);
      });
    return rows;
  }, [result, registryOrder]);

  const statusMap = useMemo(() => result?.meta?.status || {}, [result]);

  const rowData = useMemo(() => {
    if (!result) return [];
    return tableRows.map((row) => {
      const path = row.path;
      const resolved = resolvedFields?.[path];
      const activeValue = getActiveValue(path, row.value);
      const suggestions = getSuggestions(path, activeValue);
      const statusInfo = getStatusInfo(path, activeValue, suggestions);
      const reason = getReason(path, statusInfo, activeValue, suggestions);
      const evidence = getEvidence(path);
      const source = getSource(path);
      const evidenceInfo = getEvidenceLevel(evidence, statusInfo.label);
      const conflictEntry = reviewReport?.fields?.[path];
      const conflictCodes = conflictEntry?.deterministic_codes || [];
      const conflictFlag =
        Boolean(result?.meta?.conflicts?.[path]) ||
        conflictEntry?.issue_type === "CONFLICT" ||
        conflictCodes.includes("conflict_sources");
      const conflict = result?.meta?.conflicts?.[path] || null;
      const required = fieldSpecMap[path]?.required ?? false;
      return {
        path,
        resolved,
        activeValue,
        suggestions,
        statusInfo,
        reason,
        evidence,
        evidenceInfo,
        source,
        conflict,
        conflictFlag,
        required,
      };
    });
  }, [
    result,
    tableRows,
    resolvedFields,
    statusMap,
    validationSummary,
    fieldSpecMap,
  ]);

  const docMissing = useMemo(() => {
    if (!result) {
      return {
        passport: { missing: false, reason: "" },
        g28: { missing: false, reason: "" },
      };
    }
    const docMeta = result.meta?.documents || {};
    const passportMeta = docMeta.passport || null;
    const g28Meta = docMeta.g28 || null;

    const describeMismatch = (meta, label) => {
      const detected = String(meta?.detected_type || "").toLowerCase();
      if (detected === "g28") {
        return `${label} upload looks like a G-28 document. Move it to the G-28 slot.`;
      }
      if (detected === "passport") {
        return `${label} upload looks like a Passport document. Move it to the Passport slot.`;
      }
      return `${label} upload looks like a different document. Move it to the correct slot.`;
    };

    if (passportMeta?.status) {
      const status = String(passportMeta.status).toLowerCase();
      return {
        passport: {
          missing: status !== "present",
          reason:
            status === "absent"
              ? "Passport not uploaded."
              : status === "unreadable"
                ? passportMeta?.reason || "Passport unreadable (OCR/MRZ missing)."
                : status === "mismatch"
                  ? describeMismatch(passportMeta, "Passport")
                  : "",
        },
        g28: (() => {
          if (g28Meta?.status) {
            const g28Status = String(g28Meta.status).toLowerCase();
            return {
              missing: g28Status !== "present",
              reason:
                g28Status === "absent"
                  ? "G-28 not uploaded."
                  : g28Status === "unreadable"
                    ? g28Meta?.reason || "G-28 unreadable (OCR failed)."
                    : g28Status === "mismatch"
                      ? describeMismatch(g28Meta, "G-28")
                      : "",
            };
          }
          return {
            missing: !g28File,
            reason: !g28File ? "G-28 not uploaded." : "G-28 unreadable (OCR failed).",
          };
        })(),
      };
    }
    const warnings = result.meta?.warnings || [];
    const passportHasValue = rowData.some(
      (row) => row.path.startsWith("passport.") && !isEmptyValue(row.activeValue)
    );
    const g28HasValue = rowData.some(
      (row) => row.path.startsWith("g28.") && !isEmptyValue(row.activeValue)
    );
    const passportUnreadable =
      passportFile &&
      !passportHasValue &&
      warnings.some((w) => w.code === "mrz_missing" || w.code === "ingest_failed");
    const g28Unreadable =
      g28File &&
      !g28HasValue &&
      warnings.some((w) => w.code === "ingest_failed");
    return {
      passport: {
        missing: !passportFile || passportUnreadable,
        reason: !passportFile
          ? "Passport not uploaded."
          : "Passport unreadable (OCR/MRZ missing).",
      },
      g28: {
        missing: !g28File || g28Unreadable,
        reason: !g28File
          ? "G-28 not uploaded."
          : "G-28 unreadable (OCR failed).",
      },
    };
  }, [result, rowData, passportFile, g28File]);

  const missingFields = useMemo(() => {
    if (!result || !rowData.length) return [];
    const warningCodes = new Set([
      "label_present_no_value",
      "label_absent",
      "missing_required",
    ]);
    const warningMap = new Map();
    (result.meta?.warnings || []).forEach((warning) => {
      if (warning?.field && warningCodes.has(warning.code)) {
        warningMap.set(warning.field, warning.message || "");
      }
    });
    return rowData
      .filter((row) => {
        const spec = fieldSpecMap[row.path];
        if (!spec || !spec.autofill || spec.human_required) return false;
        if (docMissing.passport.missing && row.path.startsWith("passport.")) return false;
        if (docMissing.g28.missing && row.path.startsWith("g28.")) return false;
        return isEmptyValue(row.activeValue);
      })
      .map((row) => {
        const spec = fieldSpecMap[row.path] || {};
        return {
          path: row.path,
          label: fieldLabelMap[row.path] || row.path,
          required: Boolean(spec.required),
          type: spec.type || "text",
          warning: warningMap.get(row.path) || "",
        };
      });
  }, [result, rowData, fieldSpecMap, docMissing, fieldLabelMap]);

  const missingOptionalOnly = useMemo(
    () => missingFields.length > 0 && missingFields.every((field) => !field.required),
    [missingFields]
  );

  useEffect(() => {
    if (!missingFields.length) {
      setMissingDismissed(false);
    }
  }, [missingFields.length]);

  const reviewRows = useMemo(() => {
    if (!result) return [];
    const hasSummary = Boolean(reviewSummary);
    const blockingSet = new Set(reviewSummary?.blocking_fields || []);
    const reviewSet = new Set(reviewSummary?.review_fields || []);
    return rowData.map((row) => {
      let bucket = "approved";
      if (hasSummary) {
        if (blockingSet.has(row.path)) {
          bucket = "blocking";
        } else if (reviewSet.has(row.path)) {
          bucket = "review";
        }
      } else if (reviewReport?.fields?.[row.path]) {
        const entry = reviewReport.fields[row.path];
        const required = row.required;
        const status = normalizeStatus(entry.status || entry.deterministic_status || "");
        const requiresHuman = Boolean(entry.requires_human_input);
        const issueType = entry.issue_type;
        if (required && (status === "red" || requiresHuman)) {
          bucket = "blocking";
        } else if (status === "amber" || requiresHuman || issueType === "CONFLICT") {
          bucket = "review";
        }
      }
      return { ...row, reviewBucket: bucket };
    });
  }, [rowData, reviewReport, result, reviewSummary]);

  const visibleReviewRows = useMemo(() => {
    return reviewRows.filter((row) => {
      if (docMissing.passport.missing && row.path.startsWith("passport.")) return false;
      if (docMissing.g28.missing && row.path.startsWith("g28.")) return false;
      return true;
    });
  }, [reviewRows, docMissing]);

  const blockingRows = useMemo(
    () => visibleReviewRows.filter((row) => row.reviewBucket === "blocking"),
    [visibleReviewRows]
  );
  const needsReviewRows = useMemo(
    () => visibleReviewRows.filter((row) => row.reviewBucket === "review"),
    [visibleReviewRows]
  );
  const rowValueMap = useMemo(() => {
    const map = new Map();
    rowData.forEach((row) => {
      map.set(row.path, row.activeValue);
    });
    return map;
  }, [rowData]);
  const needsApprovalRows = useMemo(() => {
    if (!visibleReviewRows.length) return [];
    if (reviewSummary) {
      const actionable = new Set([
        ...(reviewSummary.blocking_fields || []),
        ...(reviewSummary.review_fields || []),
      ]);
      return visibleReviewRows.filter((row) => actionable.has(row.path));
    }
    return visibleReviewRows.filter((row) => {
      const entry = reviewReport?.fields?.[row.path];
      return Boolean(entry?.requires_human_input) || row.reviewBucket === "blocking";
    });
  }, [visibleReviewRows, reviewReport, reviewSummary]);
  const queueRows = useMemo(() => {
    if (reviewTab === "review") return needsReviewRows;
    if (reviewTab === "all") return visibleReviewRows;
    return blockingRows;
  }, [reviewTab, blockingRows, needsReviewRows, visibleReviewRows]);

  const selectedRow = useMemo(() => {
    if (!reviewRows.length) return null;
    const inQueue = queueRows.find((row) => row.path === selectedField);
    if (inQueue) return inQueue;
    const direct = reviewRows.find((row) => row.path === selectedField);
    if (direct && reviewTab === "all") return direct;
    return queueRows[0] || reviewRows[0];
  }, [reviewRows, selectedField, queueRows, reviewTab]);

  useEffect(() => {
    if (!selectedRow) return;
    const selector = `[data-queue-field="${selectedRow.path}"]`;
    const node = document.querySelector(selector);
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ block: "nearest" });
    }
  }, [selectedRow]);

  const attentionSummary = useMemo(() => {
    const summary = {
      attention: 0,
      incorrect: 0,
      missingRequired: 0,
      needsReview: 0,
      optionalMissing: 0,
      locked: 0,
      conflicts: Object.keys(result?.meta?.conflicts || {}).length,
      list: [],
      optionalList: [],
    };
    if (!result) return summary;
    const visibleRows = rowData.filter((row) => {
      if (docMissing.passport.missing && row.path.startsWith("passport.")) return false;
      if (docMissing.g28.missing && row.path.startsWith("g28.")) return false;
      return true;
    });
    visibleRows.forEach((row) => {
      if (row.resolved?.locked) summary.locked += 1;
      if (row.statusInfo.bucket === "incorrect") summary.incorrect += 1;
      if (row.statusInfo.bucket === "missing_required") summary.missingRequired += 1;
      if (row.statusInfo.bucket === "review") summary.needsReview += 1;
      if (row.statusInfo.bucket === "optional_missing") summary.optionalMissing += 1;
    });
    summary.attention = summary.incorrect + summary.missingRequired + summary.needsReview;
    const incorrectRows = visibleRows.filter((row) => row.statusInfo.bucket === "incorrect");
    const missingRows = visibleRows.filter((row) => row.statusInfo.bucket === "missing_required");
    const reviewRows = visibleRows.filter((row) => row.statusInfo.bucket === "review");
    summary.list = [...incorrectRows, ...missingRows, ...reviewRows];
    summary.optionalList = visibleRows.filter((row) => row.statusInfo.bucket === "optional_missing");
    return summary;
  }, [result, rowData, docMissing]);

  const resetRunState = () => {
    setRunId(null);
    setResult(null);
    setStatus("idle");
    setAutofillStatus(null);
    setValidationReport(null);
    setPipeline({ review: "idle", extract: "idle", autofill: "idle", validate: "idle" });
    setEditingFields({});
    setDraftValues({});
    setSaveState({});
    setReviewReport(null);
    setReviewSummary(null);
    setReviewStatus("idle");
    setReviewError(null);
    setReviewTab("blocking");
    setSelectedField(null);
    setCanonicalStatus("idle");
    setCanonicalSnapshot(null);
    setAutoApproveStatus("idle");
    setValidationAcknowledged(false);
  };

  const hasUploads = Boolean(passportFile || g28File);
  const extractedCount = useMemo(
    () => (result?.meta?.sources ? Object.keys(result.meta.sources).length : 0),
    [result]
  );
  const hasExtracted = Boolean(result && runId && pipeline.extract === "success");
  const hasExtractedData = hasExtracted && extractedCount > 0;
  const autofillRunId = autofillSummary?.run_id || runId || null;
  const hasAutofill = Boolean(autofillSummary && autofillRunId && !autofillSummary.error);
  const readyForAutofill = Boolean(reviewSummary?.ready_for_autofill);
  const hasCanonical = Boolean(canonicalSnapshot?.approved_at || result?.meta?.canonical_approved_at);
  const translationReady = Boolean(
    !translationFile ||
      languageInfo?.is_english ||
      hasTranslation ||
      translationStatus === "success"
  );
  const canExtract = hasUploads && status !== "extracting" && translationReady;
  const canAutofill = readyForAutofill && hasCanonical && pipeline.autofill !== "running";
  const canValidate = hasAutofill && pipeline.validate !== "running";
  const extractTooltip = canExtract
    ? "Ready to extract."
    : !translationReady
    ? "Translate documents before extract."
    : hasUploads
    ? "Extraction is already running."
    : "Upload a passport or G-28 to enable Extract.";
  const autofillTooltip = !readyForAutofill
    ? "Resolve blocking fields before autofill."
    : !hasCanonical
    ? "Approve canonical fields before autofill."
    : canAutofill
    ? "Ready to autofill."
    : "Autofill is already running.";
  const validateTooltip = canValidate
    ? "Ready to validate."
    : !hasAutofill
    ? "Run Autofill first."
    : "Validation is already running.";

  const translateStage = useMemo(() => {
    if (!translationFile && !languageInfo) return "idle";
    if (languageStatus === "detecting" || translationStatus === "running") return "running";
    if (languageStatus === "error" || translationStatus === "error") return "error";
    if (languageInfo?.is_english) return "skipped";
    if (hasTranslation || translationStatus === "success") return "success";
    if (languageInfo && languageStatus === "success") return "required";
    return "idle";
  }, [translationFile, languageInfo, languageStatus, translationStatus, hasTranslation]);

  const extractReviewStage = useMemo(() => {
    if (pipeline.extract === "running" || reviewStatus === "running") return "running";
    if (pipeline.extract === "error" || reviewStatus === "error") return "error";
    if (pipeline.extract === "success" && reviewStatus === "success") {
      return readyForAutofill ? "success" : "running";
    }
    if (pipeline.extract === "success") return "running";
    return "idle";
  }, [pipeline.extract, reviewStatus, readyForAutofill]);

  const stepperStages = useMemo(() => {
    return [
      { key: "translate", label: "Translate", status: translateStage },
      { key: "review", label: "Extract & Review", status: extractReviewStage },
      { key: "autofill", label: "Autofill", status: pipeline.autofill },
      { key: "validate", label: "Validate", status: pipeline.validate },
    ];
  }, [translateStage, extractReviewStage, pipeline.autofill, pipeline.validate]);

  const activeStageKey = useMemo(() => {
    const isDone = (status) => status === "success" || status === "skipped";
    const next = stepperStages.find((stage) => !isDone(stage.status));
    return next ? next.key : "validate";
  }, [stepperStages]);

  const refreshReview = async (overrideResult, overrideRunId) => {
    const activeRunId = overrideRunId || runId;
    if (!activeRunId && !overrideResult) return;
    setReviewStatus("running");
    setReviewError(null);
    setPipeline((prev) => ({ ...prev, review: "running" }));
    try {
      const response = await fetch(`${API_BASE}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: activeRunId,
          result: overrideResult || result,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || "Review failed");
      }
      if (data.result) {
        setResult(data.result);
      }
      if (data.review) {
        setReviewReport(data.review);
        setReviewSummary(data.review.summary || null);
      }
      setCanonicalStatus("idle");
      setCanonicalSnapshot(null);
      setReviewStatus("success");
      setPipeline((prev) => ({ ...prev, review: "success" }));
      setSelectedField((prev) => {
        if (prev) return prev;
        const candidates = [];
        if (data.review?.summary?.blocking_fields?.length) {
          candidates.push(...data.review.summary.blocking_fields);
        }
        if (data.review?.summary?.review_fields?.length) {
          candidates.push(...data.review.summary.review_fields);
        }
        return candidates[0] || prev;
      });
    } catch (error) {
      console.error("Review failed", error);
      setReviewStatus("error");
      setReviewError(error?.message || "Review failed");
      setPipeline((prev) => ({ ...prev, review: "error" }));
    }
  };

  const handleExtract = async () => {
    if (!hasUploads) return;
    const formData = new FormData();
    if (passportFile) formData.append("passport", passportFile);
    if (g28File) formData.append("g28", g28File);
    setStatus("extracting");
    setRunId(null);
    setResult(null);
    setAutofillStatus(null);
    setValidationReport(null);
    setValidationError(null);
    setValidationError(null);
    setValidationAcknowledged(false);
    setEditingFields({});
    setDraftValues({});
    setSaveState({});
    setReviewReport(null);
    setReviewSummary(null);
    setReviewStatus("idle");
    setReviewError(null);
    setAutoApproveStatus("idle");
    setCanonicalStatus("idle");
    setCanonicalSnapshot(null);
    setPipeline({ review: "idle", extract: "running", autofill: "idle", validate: "idle" });
    try {
      const response = await fetch(`${API_BASE}/extract`, {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || "Extraction failed");
      }
      setResult(data.result);
      setRunId(data.run_id);
      setStatus("idle");
      setPipeline((prev) => ({ ...prev, extract: "success" }));
      await refreshReview(data.result, data.run_id);
    } catch (error) {
      console.error(error);
      setStatus("error");
      setPipeline((prev) => ({ ...prev, extract: "error" }));
    }
  };

  const handleAutofill = async () => {
    if (!canAutofill) return;
    setAutofillStatus("running");
    setValidationReport(null);
    setPipeline((prev) => ({ ...prev, autofill: "running" }));
    try {
      const payload = runId ? { run_id: runId } : result;
      const response = await fetch(`${API_BASE}/autofill`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || data?.summary?.error || "Autofill failed");
      }
      setAutofillStatus({ ...data.summary, run_id: data.run_id });
      if (data?.run_id && data.run_id !== runId) {
        setRunId(data.run_id);
      }
      setPipeline((prev) => ({ ...prev, autofill: "success" }));
    } catch (error) {
      console.error(error);
      setAutofillStatus({ error: error?.message || "Autofill failed" });
      setPipeline((prev) => ({ ...prev, autofill: "error" }));
    }
  };

  const handleApproveCanonical = async () => {
    if (!runId || !readyForAutofill) return;
    setCanonicalStatus("running");
    try {
      const response = await fetch(`${API_BASE}/approve_canonical`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: runId,
          result,
          review_summary: reviewSummary,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || "Approval failed");
      }
      if (data.result) {
        setResult(data.result);
      }
      if (data.canonical) {
        setCanonicalSnapshot(data.canonical);
      }
      setCanonicalStatus("success");
    } catch (error) {
      console.error("Canonical approval failed", error);
      setCanonicalStatus("error");
    }
  };

  const handleValidate = async () => {
    if (!canValidate) return;
    const validationRunId = autofillSummary?.run_id || runId;
    if (!validationRunId) return;
    setValidationReport("running");
    setValidationAcknowledged(false);
    setValidationError(null);
    setPipeline((prev) => ({ ...prev, validate: "running" }));
    let timeoutId = null;
    try {
      const controller = new AbortController();
      timeoutId = setTimeout(() => controller.abort(), 90000);
      const response = await fetch(`${API_BASE}/post_autofill_validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: validationRunId,
          result,
          autofill_report: autofillSummary || null,
        }),
        signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || "Validation failed");
      }
      if (data.result) {
        setResult(data.result);
      }
      if (data.report) {
        setValidationReport(data.report);
      } else {
        setValidationReport(null);
      }
      setPipeline((prev) => ({ ...prev, validate: "success" }));
    } catch (error) {
      console.error(error);
      setValidationError(error?.message || "Validation failed");
      setValidationReport("error");
      setPipeline((prev) => ({ ...prev, validate: "error" }));
    } finally {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    }
  };

  const handleGoToReview = () => {
    setReviewTab("blocking");
    const el = document.getElementById("review-step");
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  const startEdit = (path) => {
    if (!result) return;
    const resolved = resolvedFields?.[path];
    const current = resolved?.value ?? getAtPath(result, path) ?? "";
    setDraftValues((prev) => ({ ...prev, [path]: current }));
    setEditingFields((prev) => ({ ...prev, [path]: true }));
    setSaveState((prev) => ({ ...prev, [path]: "idle" }));
  };

  const fieldId = (path) => `field-${String(path).replace(/[^a-zA-Z0-9_-]/g, "_")}`;


  const cancelEdit = (path) => {
    setEditingFields((prev) => {
      const next = { ...prev };
      delete next[path];
      return next;
    });
    setDraftValues((prev) => {
      const next = { ...prev };
      delete next[path];
      return next;
    });
    setSaveState((prev) => ({ ...prev, [path]: "idle" }));
  };

  const saveEdit = async (path) => {
    if (!runId) return;
    const value = draftValues[path] ?? "";
    setSaveState((prev) => ({ ...prev, [path]: "saving" }));
    try {
      const response = await fetch(`${API_BASE}/save_field_edits`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, edits: { [path]: value } }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || "Save failed");
      }
      if (data.result) {
        setResult(data.result);
      }
      await refreshReview(data.result);
      setSaveState((prev) => ({ ...prev, [path]: "saved" }));
      cancelEdit(path);
    } catch (error) {
      console.error("Save failed", error);
      setSaveState((prev) => ({ ...prev, [path]: "error" }));
    }
  };

  const handleAutoApproveAll = async () => {
    if (!runId || !result) return;
    const blocking = reviewSummary?.blocking_fields || [];
    const review = reviewSummary?.review_fields || [];
    const targets = Array.from(new Set([...blocking, ...review]));
    if (!targets.length) return;
    const edits = {};
    targets.forEach((path) => {
      const value = rowValueMap.get(path);
      if (value === undefined) {
        edits[path] = getAtPath(result, path) ?? "";
      } else {
        edits[path] = value ?? "";
      }
    });
    setAutoApproveStatus("running");
    try {
      const response = await fetch(`${API_BASE}/save_field_edits`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, edits, force: true }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || "Auto-approve failed");
      }
      if (data.result) {
        setResult(data.result);
      }
      await refreshReview(data.result || result);
      setAutoApproveStatus("success");
    } catch (error) {
      console.error("Auto-approve failed", error);
      setAutoApproveStatus("error");
    }
  };

  const handleTranslate = async () => {
    if (!translationFile && !languageInfo?.run_id) return;
    setTranslationStatus("running");
    setTranslationError(null);
    try {
      const formData = new FormData();
      if (languageInfo?.run_id) {
        formData.append("run_id", languageInfo.run_id);
      } else if (translationFile) {
        formData.append("document", translationFile);
      }
      if (languageInfo?.doc_type || translationDocType) {
        formData.append("doc_type", languageInfo?.doc_type || translationDocType);
      }
      if (ocrLangOverride && ocrLangOverride !== "auto") {
        formData.append("ocr_langs", ocrLangOverride);
      }
      const response = await fetch(`${API_BASE}/translate`, {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || "Translation failed");
      }
      setTranslatedText(data.translated_text || "");
      setTranslationRunId(data.run_id || languageInfo?.run_id || null);
      setTranslationArtifacts(data.artifacts || null);
      setTextActive(data?.text_active || "translated_en");
      setHasTranslation(true);
      setTranslationWarning(data?.translation_warning || null);
      setTranslationStatus("success");
      if (data.detected_language) {
        setLanguageInfo((prev) => ({ ...(prev || {}), ...data }));
      }
    } catch (error) {
      console.error("Translation failed", error);
      setTranslationStatus("error");
      setTranslationError(error?.message || "Translation failed");
    }
  };

  const handleActiveChange = async (nextActive) => {
    if (!nextActive || nextActive === textActive) return;
    const activeRunId = languageInfo?.run_id || translationRunId;
    const activeDocType = languageInfo?.doc_type || translationDocType;
    if (!activeRunId || !activeDocType) {
      setActiveError("Missing run or document type.");
      return;
    }
    setActiveStatus("saving");
    setActiveError(null);
    try {
      const formData = new FormData();
      formData.append("run_id", activeRunId);
      formData.append("doc_type", activeDocType);
      formData.append("active", nextActive);
      const response = await fetch(`${API_BASE}/text_artifact/active`, {
        method: "POST",
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || "Unable to update active text");
      }
      setTextActive(data?.text_active || nextActive);
      setTranslationWarning(data?.translation_warning || null);
      setActiveStatus("success");
    } catch (error) {
      console.error("Active text update failed", error);
      setActiveStatus("error");
      setActiveError(error?.message || "Unable to update active text");
    }
  };

  const handleCopy = async (text) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch (error) {
      console.error("Copy failed", error);
    }
  };

  const handleDrop = (event, kind) => {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (file) {
      resetRunState();
      if (kind === "passport") {
        setPassportFile(file);
      } else {
        setG28File(file);
      }
    }
    setDragState((prev) => ({ ...prev, [kind]: false }));
  };

  const renderDropzone = (kind, label, file, accept) => {
    const isActive = dragState[kind];
    return (
      <div
        className={`dropzone ${isActive ? "active" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragState((prev) => ({ ...prev, [kind]: true }));
        }}
        onDragLeave={() => setDragState((prev) => ({ ...prev, [kind]: false }))}
        onDrop={(e) => handleDrop(e, kind)}
        onClick={() => document.getElementById(`${kind}-input`)?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            document.getElementById(`${kind}-input`)?.click();
          }
        }}
        role="button"
        tabIndex={0}
      >
        <input
          id={`${kind}-input`}
          type="file"
          accept={accept}
          className="hidden-input"
          onChange={(e) => {
            const nextFile = e.target.files?.[0];
            if (nextFile) {
              resetRunState();
              if (kind === "passport") {
                setPassportFile(nextFile);
              } else {
                setG28File(nextFile);
              }
            }
          }}
        />
        <div className="dropzone-content">
          <p className="drop-title">{label}</p>
          <p className="drop-hint">
            {file ? file.name : "Drag & drop or click to browse"}
          </p>
        </div>
      </div>
    );
  };

  const applySuggestions = () => {
    if (!result?.meta?.suggestions) return;
    Object.entries(result.meta.suggestions || {}).forEach(([path, suggestions]) => {
      if (!Array.isArray(suggestions) || !suggestions.length) return;
      const filtered = getSuggestions(path, getActiveValue(path, getAtPath(result, path)));
      const best = [...filtered].sort(
        (a, b) => (b.confidence || 0) - (a.confidence || 0)
      )[0];
      if (best && best.value) {
        applySuggestionForPath(path, best);
      }
    });
  };

  const applySuggestionsBySource = (sourceKey, minScore = 0) => {
    if (!result?.meta?.suggestions) return;
    Object.entries(result.meta.suggestions || {}).forEach(([path, suggestions]) => {
      if (!Array.isArray(suggestions) || !suggestions.length) return;
      const filtered = getSuggestions(path, getActiveValue(path, getAtPath(result, path)));
      const best = [...filtered]
        .filter(
          (suggestion) =>
            suggestion.source === sourceKey &&
            !suggestion.requires_confirmation &&
            (suggestion.confidence ?? 0) >= minScore
        )
        .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))[0];
      if (best && best.value) {
        applySuggestionForPath(path, best);
      }
    });
  };

  const applySuggestionForPath = (path, suggestion) => {
    const value = suggestion?.value ?? "";
    const source = suggestion?.source || "";
    const confidence = typeof suggestion?.confidence === "number" ? suggestion.confidence : 0.7;
    const evidence = suggestion?.evidence || "";
    let nextResult = null;
    setResult((prev) => {
      if (!prev) return prev;
      let next = setAtPath(prev, path, value);
      const isAi = source?.toLowerCase() === "llm";
      const evidenceText =
        evidence || (isAi ? "AI suggestion (LLM)" : "Validator suggestion");
      const isValid = validateValue(path, value).valid;
      const nextStatus = !value
        ? "red"
        : isValid
        ? confidence >= 0.85
          ? "green"
          : "amber"
        : "red";
      const storedStatus = nextStatus;
      const resolvedMap = { ...(next.meta?.resolved_fields || {}) };
      const priorResolved = resolvedMap[path] || {};
      const nowIso = new Date().toISOString();
      resolvedMap[path] = {
        ...priorResolved,
        key: path,
        value,
        status: storedStatus,
        confidence: isAi ? confidence : 1.0,
        source: isAi ? "AI" : "USER",
        locked: true,
        requires_human_input: storedStatus !== "green",
        reason: evidenceText,
        suggestions: priorResolved.suggestions || [],
        last_validated_at: nowIso,
        version: (priorResolved.version ?? 0) + 1,
      };
      const nextConflicts = { ...(next.meta?.conflicts || {}) };
      delete nextConflicts[path];
      const nextWarnings = (next.meta?.warnings || []).filter(
        (warning) => !(warning.code === "conflict" && warning.field === path)
      );
      const nextSuggestions = { ...(next.meta?.suggestions || {}) };
      delete nextSuggestions[path];
      next = {
        ...next,
        meta: {
          ...next.meta,
          sources: {
            ...(next.meta?.sources || {}),
            [path]: isAi ? "AI" : "USER",
          },
          confidence: {
            ...(next.meta?.confidence || {}),
            [path]: isAi ? confidence : 1.0,
          },
          status: {
            ...(next.meta?.status || {}),
            [path]: nextStatus,
          },
          evidence: {
            ...(next.meta?.evidence || {}),
            [path]: evidenceText,
          },
          conflicts: nextConflicts,
          warnings: nextWarnings,
          suggestions: nextSuggestions,
          resolved_fields: resolvedMap,
        },
      };
      nextResult = next;
      return next;
    });
    if (nextResult) {
      refreshReview(nextResult);
    }
  };

  const applyConfirmedValue = async (path, value, reason) => {
    if (!runId) {
      let nextResult = null;
      setResult((prev) => {
        if (!prev) return prev;
        let next = setAtPath(prev, path, value);
        const resolvedMap = { ...(next.meta?.resolved_fields || {}) };
        const priorResolved = resolvedMap[path] || {};
        const nowIso = new Date().toISOString();
        resolvedMap[path] = {
          ...priorResolved,
          key: path,
          value,
          status: "green",
          confidence: 1.0,
          source: "USER",
          locked: true,
          requires_human_input: false,
          reason,
          suggestions: priorResolved.suggestions || [],
          last_validated_at: nowIso,
          version: (priorResolved.version ?? 0) + 1,
        };
        const nextConflicts = { ...(next.meta?.conflicts || {}) };
        delete nextConflicts[path];
        const nextWarnings = (next.meta?.warnings || []).filter(
          (warning) => !(warning.code === "conflict" && warning.field === path)
        );
        const nextSuggestions = { ...(next.meta?.suggestions || {}) };
        delete nextSuggestions[path];
        next = {
          ...next,
          meta: {
            ...next.meta,
            sources: {
              ...(next.meta?.sources || {}),
              [path]: "USER",
            },
            confidence: {
              ...(next.meta?.confidence || {}),
              [path]: 1.0,
            },
            status: {
              ...(next.meta?.status || {}),
              [path]: "green",
            },
            evidence: {
              ...(next.meta?.evidence || {}),
              [path]: reason,
            },
            conflicts: nextConflicts,
            warnings: nextWarnings,
            suggestions: nextSuggestions,
            resolved_fields: resolvedMap,
          },
        };
        nextResult = next;
        return next;
      });
      if (nextResult) {
        refreshReview(nextResult);
      }
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/save_field_edits`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: runId,
          edits: { [path]: value },
          force: true,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || "Save failed");
      }
      if (data.result) {
        setResult(data.result);
      }
      await refreshReview(data.result);
    } catch (error) {
      console.error("Conflict resolve save failed", error);
    }
  };

  const applyConflictValue = (path, value, sourceLabel) => {
    applyConfirmedValue(path, value, `Conflict resolved: ${sourceLabel}`);
  };

  const handleSaveMissingFields = async () => {
    if (!missingFields.length) return;
    setMissingSaveError(null);
    const edits = {};
    missingFields.forEach((field) => {
      const raw = missingDrafts[field.path];
      if (raw === undefined || raw === null) return;
      const value = String(raw).trim();
      if (value) edits[field.path] = value;
    });
    if (!Object.keys(edits).length) {
      setMissingSaveError("Enter at least one value before saving.");
      return;
    }
    setMissingSaveState("saving");

    if (!runId) {
      for (const [path, value] of Object.entries(edits)) {
        // Treat missing-field fills like conflict resolution (user-confirmed).
        // eslint-disable-next-line no-await-in-loop
        await applyConfirmedValue(path, value, "User filled missing field.");
      }
      setMissingSaveState("saved");
      setMissingDrafts((prev) => {
        const next = { ...prev };
        Object.keys(edits).forEach((key) => delete next[key]);
        return next;
      });
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/save_field_edits`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: runId,
          edits,
          force: true,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.error || "Save failed");
      }
      if (data.result) {
        setResult(data.result);
      }
      await refreshReview(data.result);
      setMissingSaveState("saved");
      setMissingDrafts((prev) => {
        const next = { ...prev };
        Object.keys(edits).forEach((key) => delete next[key]);
        return next;
      });
    } catch (error) {
      console.error("Missing field save failed", error);
      setMissingSaveState("error");
      setMissingSaveError(error?.message || "Save failed");
    }
  };

  const renderMissingInput = (field) => {
    const value = missingDrafts[field.path] ?? "";
    const onChange = (event) => {
      const nextValue = event.target.value;
      setMissingDrafts((prev) => ({ ...prev, [field.path]: nextValue }));
    };
    if (field.type === "checkbox") {
      return (
        <select value={value} onChange={onChange}>
          <option value="">Select…</option>
          <option value="yes">Yes</option>
          <option value="no">No</option>
        </select>
      );
    }
    if (field.type === "sex") {
      return (
        <select value={value} onChange={onChange}>
          <option value="">Select…</option>
          <option value="M">M</option>
          <option value="F">F</option>
          <option value="X">X</option>
        </select>
      );
    }
    if (field.type === "date_past" || field.type === "date_future") {
      return <input type="date" value={value} onChange={onChange} />;
    }
    if (field.type === "email") {
      return <input type="email" value={value} onChange={onChange} placeholder="name@example.com" />;
    }
    if (field.type === "phone") {
      return <input type="tel" value={value} onChange={onChange} placeholder="(555) 555-5555" />;
    }
    if (field.type === "state") {
      return <input value={value} onChange={onChange} maxLength={2} placeholder="CA" />;
    }
    if (field.type === "zip") {
      return <input value={value} onChange={onChange} inputMode="numeric" placeholder="94108" />;
    }
    return <input value={value} onChange={onChange} placeholder="Enter value" />;
  };

  const summarySnapshot = useMemo(() => {
    if (reviewSummary) return reviewSummary;
    return {
      blocking: 0,
      needs_review: 0,
      auto_approved: 0,
      optional_missing: 0,
      required_missing: 0,
      conflicts: 0,
      total: 0,
      blocking_fields: [],
      review_fields: [],
      auto_fields: [],
      ready_for_autofill: false,
    };
  }, [reviewSummary]);

  const otherWarnings = useMemo(() => {
    const warnings = result?.meta?.warnings || [];
    if (!warnings.length) return [];
    const missingPaths = new Set(missingFields.map((field) => field.path));
    const missingCodes = new Set([
      "label_present_no_value",
      "label_absent",
      "missing_required",
    ]);
    return warnings.filter((warning) => {
      if (!warning?.field) return true;
      if (!missingPaths.has(warning.field)) return true;
      return !missingCodes.has(warning.code);
    });
  }, [result, missingFields]);

  const reviewRemaining = useMemo(() => {
    const blocking = Number(summarySnapshot?.blocking || 0);
    const needsReview = Number(summarySnapshot?.needs_review || 0);
    return Math.max(0, blocking + needsReview);
  }, [summarySnapshot]);

  const formCompleteness = validationSummary?.form_completeness || null;
  const validationRows = useMemo(() => {
    if (!validationSummary?.fields) return [];
    const mapped = formCompleteness?.mapped || {};
    return Object.entries(validationSummary.fields).map(([path, entry]) => {
      const value =
        entry?.dom_readback_value ??
        entry?.extracted_value ??
        "";
      const source = getSource(path) || "unknown";
      const evidence = getEvidence(path);
      const heuristicVerdict =
        entry?.deterministic_validation?.status ||
        entry?.deterministic_status ||
        entry?.deterministic_validation?.verdict ||
        "";
      const heuristicReason =
        entry?.deterministic_validation?.reason ||
        entry?.deterministic_reason ||
        "";
      const llmInvoked = Boolean(entry?.llm_validation_invoked || entry?.llm_validation);
      const llmVerdict = llmInvoked
        ? entry?.llm_validation?.verdict ||
          entry?.llm_verdict ||
          entry?.llm_validation?.status ||
          ""
        : "";
      const llmReason =
        entry?.llm_validation?.reason ||
        entry?.llm_reason ||
        "";
      const llmEvidence =
        entry?.llm_validation?.evidence ||
        entry?.llm_evidence ||
        "";
      const requiresHuman = Boolean(
        entry?.requires_human_input || entry?.llm_requires_human_input
      );
      const humanReason = entry?.human_reason || "";
      const humanAction = entry?.human_action || "";
      const mappedEntry = mapped?.[path] || null;
      const finalStatus = normalizeStatus(
        entry?.status || entry?.deterministic_status || entry?.deterministic_validation?.status || ""
      );
      const formFilled =
        mappedEntry && !mappedEntry.unmapped ? Boolean(mappedEntry.filled) : null;
      const formRequired =
        mappedEntry && !mappedEntry.unmapped ? Boolean(mappedEntry.required) : null;
      const isCompleted = formFilled === true && finalStatus === "green" && !requiresHuman;
      const fieldType = fieldTypeMap[path] || "";
      const issueTags = new Set();
      const issueLabel = formatIssueLabel(entry?.issue_type);
      if (issueLabel) issueTags.add(issueLabel);
      if (requiresHuman && issueLabel !== "Needs consent") {
        issueTags.add("Needs human input");
      }
      if (mappedEntry?.unmapped && mappedEntry?.required) {
        issueTags.add("Unmapped required");
      }
      if (mappedEntry?.issue === "AUTOFILL_MISSED" && mappedEntry?.required) {
        issueTags.add(formatIssueLabel("AUTOFILL_MISSED"));
      }
      if (Array.isArray(entry?.deterministic_codes)) {
        if (entry.deterministic_codes.some((code) => String(code).startsWith("autofill_"))) {
          issueTags.add("Autofill failed");
        }
        if (entry.deterministic_codes.includes("conflict_sources")) {
          issueTags.add("Conflict");
        }
      }
      return {
        path,
        label: fieldLabelMap[path] || path,
        value: normalizeValue(value) || "—",
        source,
        hasEvidence: Boolean(evidence),
        issues: Array.from(issueTags).filter(Boolean),
        heuristicVerdict,
        heuristicReason,
        llmInvoked,
        llmVerdict,
        llmReason,
        llmEvidence,
        requiresHuman,
        humanReason,
        humanAction,
        formRequired,
        formFilled,
        finalStatus,
        isCompleted,
        fieldType,
      };
    });
  }, [validationSummary, fieldLabelMap, formCompleteness, getEvidence, getSource, fieldTypeMap]);

  const validationCounts = useMemo(() => {
    const total = validationRows.length;
    const human = validationRows.filter((row) => row.requiresHuman).length;
    const completed = validationRows.filter((row) => row.isCompleted).length;
    const needsAttention = validationRows.filter(
      (row) => !row.isCompleted && !row.requiresHuman
    ).length;
    return { total, human, completed, needsAttention };
  }, [validationRows]);

  const filteredValidationRows = useMemo(() => {
    if (validationFilter === "human") {
      return validationRows.filter((row) => row.requiresHuman);
    }
    if (validationFilter === "completed") {
      return validationRows.filter((row) => row.isCompleted);
    }
    return validationRows;
  }, [validationRows, validationFilter]);

  useEffect(() => {
    if (!validationSummary) return;
    setValidationFilter((prev) => {
      if (prev === "all") return prev;
      return validationCounts.human > 0 ? "human" : "completed";
    });
  }, [validationSummary, validationCounts.human]);

  const formCounts = formCompleteness?.counts || {};
  const requiredNotFilled = Number(formCounts.required_not_filled || 0);
  const unmappedRequired = Number(formCounts.unmapped_required || 0);
  const optionalNotFilled = Number(formCounts.optional_not_filled || 0);
  const requiredMissing = requiredNotFilled + unmappedRequired;
  const formCompletenessItems = [
    { key: "required", label: "Required missing", count: requiredNotFilled, tone: "red" },
    { key: "unmapped", label: "Unmapped required", count: unmappedRequired, tone: "yellow" },
    { key: "optional", label: "Optional missing", count: optionalNotFilled, tone: "unknown" },
  ].filter((item) => item.count > 0);

  return (
    <div className="app">
      <header className="hero">
        <div>
          <p className="eyebrow">Doc Extractor</p>
          <h1>Passport + G-28 extraction with confidence trails.</h1>
          <p className="subtext">
            Upload a passport and USCIS G-28, then extract, autofill, and validate.
          </p>
        </div>
        <div className="hero-card">
          <div className="dropzone-grid">
            {renderDropzone("passport", "Passport (PDF/Image)", passportFile, ".pdf,image/*")}
            {renderDropzone("g28", "G-28 (PDF/Image)", g28File, ".pdf,image/*")}
          </div>
          {runId && <p className="run">Run ID: {runId}</p>}
          {pipeline.extract === "success" && hasExtractedData && (
            <p className="note">Extraction complete — {extractedCount} fields detected.</p>
          )}
          {pipeline.extract === "success" && !hasExtractedData && (
            <p className="warning">
              Extraction completed but no fields were detected. Check document quality or upload again.
            </p>
          )}
        </div>
      </header>

      <div className="stepper">
        {stepperStages.map((stage) => {
          let meta = "Not started";
          if (stage.status === "success") {
            meta = stage.key === "translate" ? "Translation completed" : "Done";
          } else if (stage.status === "skipped") {
            meta = "Skipped — English detected";
          } else if (stage.status === "required") {
            meta = "Translation required";
          } else if (stage.status === "running") {
            meta = "In progress";
          } else if (stage.status === "error") {
            meta = "Needs attention";
          }
          return (
            <div
              key={stage.key}
              className={`step ${stage.status} ${activeStageKey === stage.key ? "active" : ""}`}
            >
              <div className="step-label">{stage.label}</div>
              <div className="step-meta">{meta}</div>
            </div>
          );
        })}
      </div>

      {showTranslationPanel && (
      <section className="panel step-panel translation-panel">
        <div className="panel-header">
          <div>
            <p className="step-eyebrow">Step 1</p>
            <h2>Translate (if needed)</h2>
          </div>
          {translationSource && <span className="chip">Source: {translationSource}</span>}
        </div>
        <div className="translation-row">
          <p className="status-label">Language</p>
          {languageStatus === "detecting" && <p className="note">Detecting language…</p>}
          {languageStatus === "error" && <p className="error">{languageError}</p>}
          {languageInfo && languageStatus === "success" && (
            <p className="status-value">
              Detected language: {languageInfo.language_name || languageInfo.detected_language || "Unknown"} (
              {typeof languageInfo.language_confidence === "number"
                ? languageInfo.language_confidence.toFixed(2)
                : "—"}
              )
            </p>
          )}
        </div>
        <div className="translation-row">
          <p className="status-label">OCR language</p>
          <label className="toggle">
            <span>Override</span>
            <select
              value={ocrLangOverride}
              onChange={(event) => setOcrLangOverride(event.target.value)}
              disabled={languageStatus === "detecting" || translationStatus === "running"}
            >
              <option value="auto">Auto (detect)</option>
              <option value="spa+eng">Spanish (spa+eng)</option>
              <option value="chi_sim+eng">Chinese (chi_sim+eng)</option>
            </select>
          </label>
          <p className="note">Forces OCR language during detection and translation.</p>
        </div>
        {languageInfo && languageStatus === "success" && (
          <div className="translation-row">
            <p className="status-label">Active text</p>
            <div className="toggle-group">
              <label className="toggle-option">
                <input
                  type="radio"
                  name="text-active"
                  value="raw"
                  checked={textActive === "raw"}
                  onChange={() => handleActiveChange("raw")}
                />
                Raw OCR
              </label>
              <label className={`toggle-option ${hasTranslation ? "" : "disabled"}`}>
                <input
                  type="radio"
                  name="text-active"
                  value="translated_en"
                  checked={textActive === "translated_en"}
                  disabled={!hasTranslation}
                  onChange={() => handleActiveChange("translated_en")}
                />
                Translated English
              </label>
            </div>
            {activeStatus === "saving" && <p className="note">Saving active text…</p>}
            {activeStatus === "error" && <p className="error">{activeError}</p>}
          </div>
        )}
        {translationWarning && (
          <p className="warning">Translation may reduce extraction quality. {translationWarning}</p>
        )}
          {languageInfo && languageStatus === "success" && languageInfo.is_english && (
          <p className="note">Skipped — English detected.</p>
        )}
        {languageInfo && languageStatus === "success" && !languageInfo.is_english && (
          <p className="note">Translation required before extraction.</p>
        )}
        {languageInfo && languageStatus === "success" && !languageInfo.is_english && (
          <div className="translation-cta">
            <p className="translation-warning">
              This document appears to be in {languageInfo.language_name || languageInfo.detected_language}.
              Translation can help downstream extraction.
            </p>
            <div className="action-row">
              <button
                className="secondary"
                onClick={handleTranslate}
                disabled={translationStatus === "running"}
              >
                {translationStatus === "running" ? "Translating..." : "Translate"}
              </button>
            </div>
            <p className="note">Translation generates an English text artifact for later extraction.</p>
          </div>
        )}
        {languageInfo &&
          languageStatus === "success" &&
          !languageInfo.is_english &&
          (hasTranslation || translationStatus === "success") && (
            <p className="note">Translation completed.</p>
          )}
        {translationStatus === "success" && (
          <div className="status">
            <div className="status-grid">
              <div>
                <p className="status-label">Translation run</p>
                <p className="status-value">{translationRunId || languageInfo?.run_id || "—"}</p>
              </div>
              <div>
                <p className="status-label">Artifacts</p>
                <p className="status-value">Saved to run artifacts</p>
              </div>
            </div>
            {translatedTextPath && (
              <div className="status-row">
                <span className="mono">{translatedTextPath}</span>
                <button className="ghost" onClick={() => handleCopy(translatedTextPath)}>
                  Copy
                </button>
              </div>
            )}
            {translatedOcrPath && (
              <div className="status-row">
                <span className="mono">{translatedOcrPath}</span>
                <button className="ghost" onClick={() => handleCopy(translatedOcrPath)}>
                  Copy
                </button>
              </div>
            )}
            <details className="translation-preview">
              <summary>Preview translated text</summary>
              <pre>{translatedText || "—"}</pre>
            </details>
          </div>
        )}
        {translationStatus === "error" && (
          <p className="error">Translation failed: {translationError || "Unknown error"}</p>
        )}
      </section>
      )}

      <section className="panel step-panel" id="review-step">
        <div className="panel-header">
          <div>
            <p className="step-eyebrow">Step 2</p>
            <h2>Extract & Review</h2>
            <p className="note">Run extraction, then resolve conflicts before autofill.</p>
          </div>
          <div className="action-buttons">
            <button
              className="primary"
              onClick={handleExtract}
              disabled={!canExtract}
              title={extractTooltip}
            >
              {status === "extracting" ? "Extracting..." : "Run extraction"}
            </button>
            <button
              className="ghost"
              onClick={() => refreshReview()}
              disabled={!hasExtracted}
              title={!hasExtracted ? "Run extraction first." : "Re-run review checks"}
            >
              Re-run checks
            </button>
          </div>
        </div>

        {runId && <p className="run">Run ID: {runId}</p>}
        {reviewStatus === "running" && <p className="note">Running rule checks…</p>}
        {reviewError && <p className="error">Review failed: {reviewError}</p>}

        {(hasExtracted || reviewSummary) && (
          <div className="summary-bar">
            <span>Blocking: {summarySnapshot.blocking}</span>
            <span>Needs review: {summarySnapshot.needs_review}</span>
            <span>Auto-approved: {summarySnapshot.auto_approved}</span>
            {summarySnapshot.optional_missing > 0 && (
              <span>Optional blank: {summarySnapshot.optional_missing}</span>
            )}
          </div>
        )}

        {needsApprovalRows.length > 0 && (
          <div className="status attention-panel">
            <div className="status-grid">
              <div>
                <p className="status-label">Needs human approval</p>
                <p className="status-value">{needsApprovalRows.length} fields</p>
              </div>
            </div>
            <ul className="status-list">
              {needsApprovalRows.map((row) => {
                const entry = reviewReport?.fields?.[row.path];
                const label = fieldLabelMap[row.path] || row.path;
                const conflictInfo = result?.meta?.conflicts?.[row.path];
                const conflictSummary = conflictInfo
                  ? conflictInfo.mrz_value || conflictInfo.ocr_value
                    ? `MRZ: ${conflictInfo?.mrz_value || "—"} vs OCR: ${conflictInfo?.ocr_value || "—"} (mismatch)`
                    : `Passport: ${conflictInfo?.passport_value || "—"} vs G-28: ${conflictInfo?.g28_value || "—"} (mismatch)`
                  : "";
                const reason =
                  conflictSummary ||
                  entry?.human_reason ||
                  entry?.deterministic_reason ||
                  entry?.llm_reason ||
                  "";
                return (
                  <li key={row.path}>
                    <span className="mono">{label}</span>
                    {reason ? ` — ${reason}` : ""}
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {docMissing.passport.missing && (
          <div className="banner warning">
            Passport document unavailable — {passportFieldCount} passport fields cannot be extracted.
            <span className="note">{docMissing.passport.reason}</span>
          </div>
        )}
        {docMissing.g28.missing && (
          <div className="banner warning">
            G-28 document unavailable — {g28FieldCount} G-28 fields cannot be extracted.
            <span className="note">{docMissing.g28.reason}</span>
          </div>
        )}

        {hasExtracted ? (
          <div className="review-layout">
            <div className="queue-panel">
              <div className="queue-tabs">
                <button
                  className={`queue-tab ${reviewTab === "blocking" ? "active" : ""}`}
                  onClick={() => setReviewTab("blocking")}
                >
                  Blocking ({blockingRows.length})
                </button>
                <button
                  className={`queue-tab ${reviewTab === "review" ? "active" : ""}`}
                  onClick={() => setReviewTab("review")}
                >
                  Needs review ({needsReviewRows.length})
                </button>
                <button
                  className={`queue-tab ${reviewTab === "all" ? "active" : ""}`}
                  onClick={() => setReviewTab("all")}
                >
                  All fields ({visibleReviewRows.length})
                </button>
              </div>
              <div className="queue-list">
                {queueRows.map((row) => {
                  const displayValue = normalizeValue(row.activeValue);
                  const fieldLabel = fieldLabelMap[row.path] || row.path;
                  return (
                    <button
                      type="button"
                      key={row.path}
                      data-queue-field={row.path}
                      data-has-suggestions={row.suggestions.length > 0 ? "true" : "false"}
                      data-review-bucket={row.reviewBucket}
                      className={`queue-item ${selectedRow?.path === row.path ? "active" : ""}`}
                      onClick={() => setSelectedField(row.path)}
                    >
                      <div className="queue-item-header">
                        <div className="field-meta">
                          <div className="field-label">{fieldLabel}</div>
                        </div>
                      </div>
                    </button>
                  );
                })}
                {!queueRows.length && (
                  <div className="queue-empty">No fields in this queue.</div>
                )}
              </div>
            </div>

            <div className="detail-panel">
              {selectedRow ? (
                (() => {
                  const row = selectedRow;
                  const displayValue = normalizeValue(row.activeValue);
                  const isEditing = Boolean(editingFields[row.path]);
                  const isEmpty = isEmptyValue(row.activeValue);
                  const fieldLabel = fieldLabelMap[row.path] || row.path;
                  const detailStatus = reviewSummary
                    ? row.reviewBucket === "blocking"
                      ? { label: "Blocking", tone: "red" }
                      : row.reviewBucket === "review"
                      ? { label: "Needs review", tone: "yellow" }
                      : { label: "Approved", tone: "green" }
                    : row.statusInfo;
                  const evidenceSnippet = row.evidence.length > 160
                    ? `${row.evidence.slice(0, 160).trim()}…`
                    : row.evidence;
                  const hasLongEvidence = row.evidence.length > 160;
                  const rulesCheck = getRulesCheck(row.path);
                  const llmCheck = getLlmCheck(row.path);
                  const conflictInfo = row.conflict;
                  const conflictCandidates = [];
                  if (conflictInfo?.mrz_value) {
                    conflictCandidates.push({ label: "MRZ", value: conflictInfo.mrz_value });
                  }
                  if (conflictInfo?.ocr_value) {
                    conflictCandidates.push({ label: "OCR", value: conflictInfo.ocr_value });
                  }
                  if (conflictInfo?.passport_value) {
                    conflictCandidates.push({ label: "Passport", value: conflictInfo.passport_value });
                  }
                  if (conflictInfo?.g28_value) {
                    conflictCandidates.push({ label: "G-28", value: conflictInfo.g28_value });
                  }
                  const conflictSummary = (() => {
                    if (!row.conflictFlag) return "";
                    if (conflictInfo?.mrz_value || conflictInfo?.ocr_value) {
                      return `MRZ: ${conflictInfo?.mrz_value || "—"} vs OCR: ${conflictInfo?.ocr_value || "—"} (mismatch)`;
                    }
                    if (conflictInfo?.passport_value || conflictInfo?.g28_value) {
                      return `Passport: ${conflictInfo?.passport_value || "—"} vs G-28: ${conflictInfo?.g28_value || "—"} (mismatch)`;
                    }
                    return "Conflict between credible sources; user confirmation required.";
                  })();
                  return (
                    <div
                      className="field-row"
                      id={fieldId(row.path)}
                      data-detail-field={row.path}
                    >
                      <div className="field-left">
                        <div className="field-tags">
                          <span className={`status-pill ${detailStatus.tone}`}>{detailStatus.label}</span>
                          {row.resolved?.locked && <span className="chip chip-locked">Locked</span>}
                        </div>
                        <div className="field-meta">
                          <div className="field-label">{fieldLabel}</div>
                          <div className="field-key mono">{row.path}</div>
                        </div>
                      </div>
                      <div className="field-middle">
                        {isEditing ? (
                          <div className="value-edit">
                            <input
                              value={draftValues[row.path] ?? ""}
                              onChange={(e) =>
                                setDraftValues((prev) => ({ ...prev, [row.path]: e.target.value }))
                              }
                              placeholder="—"
                            />
                            <div className="value-actions">
                              <button className="ghost" onClick={() => saveEdit(row.path)} disabled={!runId}>
                                {saveState[row.path] === "saving" ? "Saving..." : "Save"}
                              </button>
                              <button className="ghost" onClick={() => cancelEdit(row.path)}>
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="value-line">
                            <span className={`value-text ${isEmpty ? "placeholder" : ""}`}>
                              {displayValue || "—"}
                            </span>
                            <div className="value-actions">
                              <button className="ghost" onClick={() => startEdit(row.path)}>
                                Edit
                              </button>
                            </div>
                          </div>
                        )}
                        {row.reason && <div className="value-reason">{row.reason}</div>}
                        {row.conflictFlag && conflictSummary && (
                          <div className="note">{conflictSummary}</div>
                        )}
                        {row.conflictFlag && conflictCandidates.length > 0 && (
                          <div className="conflict-candidates">
                            <p className="note">Choose the correct value:</p>
                            <div className="action-row">
                              {conflictCandidates.map((candidate) => (
                                <button
                                  className="ghost"
                                  key={`${row.path}-${candidate.label}`}
                                  onClick={() => applyConflictValue(row.path, candidate.value, candidate.label)}
                                >
                                  Use {candidate.label}
                                </button>
                              ))}
                            </div>
                          </div>
                        )}
                        {(rulesCheck || llmCheck) && (
                          <div className="validator-checks">
                            {rulesCheck && (
                              <div className="validator-line">
                                <span>Rules check</span>
                                <span className={`status-chip ${rulesCheck.tone}`}>{rulesCheck.label}</span>
                              </div>
                            )}
                            {llmCheck && (
                              <div className="validator-line">
                                <span>LLM check</span>
                                <span className={`status-chip ${llmCheck.tone}`}>{llmCheck.label}</span>
                              </div>
                            )}
                          </div>
                        )}
                        {row.suggestions.length > 0 && !row.conflictFlag && (
                          <div className="suggestion-stack">
                            {row.suggestions.map((suggestion, idx) => (
                              <div className="suggestion-card" key={`${row.path}-suggestion-${idx}`}>
                                <div className="suggestion-header">
                                  <span className="suggestion-title">Suggested</span>
                                  <span className="mono">{suggestion.value}</span>
                                  <button
                                    className="ghost"
                                    onClick={() => applySuggestionForPath(row.path, suggestion)}
                                  >
                                    Apply & lock
                                  </button>
                                </div>
                                <div className="suggestion-meta">
                                  <span
                                    className={`chip ${
                                      String(suggestion.source || "").toUpperCase() === "LLM"
                                        ? "chip-ai"
                                        : "chip-heuristic"
                                    }`}
                                  >
                                    {getSuggestionSourceLabel(suggestion.source)}
                                  </span>
                                  {suggestion.reason && (
                                    <span className="suggestion-reason">{suggestion.reason}</span>
                                  )}
                                  {suggestion.requires_confirmation && (
                                    <span className="chip chip-warning">Needs confirmation</span>
                                  )}
                                </div>
                                <div className="suggestion-evidence">{suggestion.evidence}</div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="field-right">
                        <div className="evidence-meta">
                          {row.source ? (
                            <span className={`chip source-${row.source.toLowerCase()}`}>
                              {row.source}
                            </span>
                          ) : (
                            <span className="chip chip-muted">No source</span>
                          )}
                          <span className={`chip evidence-${row.evidenceInfo.level}`}>{row.evidenceInfo.label}</span>
                        </div>
                        {row.evidence ? (
                          <>
                            <div className="evidence-text">{evidenceSnippet}</div>
                            {hasLongEvidence && (
                              <details className="evidence-expand">
                                <summary>View more</summary>
                                <pre>{row.evidence}</pre>
                              </details>
                            )}
                          </>
                        ) : (
                          <div className="evidence-text muted">No evidence snippet.</div>
                        )}
                      </div>
                    </div>
                  );
                })()
              ) : (
                <div className="table-row empty">Select a field to review.</div>
              )}
            </div>
          </div>
        ) : (
          <p className="note">Upload documents and run extraction to start review.</p>
        )}

        {readyForAutofill && (
          <div className="banner success">Review complete — ready for autofill.</div>
        )}
        <div className="review-cta">
          <button
            className="primary"
            onClick={handleApproveCanonical}
            disabled={!readyForAutofill || canonicalStatus === "running"}
            aria-label="Approve canonical fields"
          >
            {canonicalStatus === "running"
              ? "Approving..."
              : readyForAutofill
              ? "Proceed to Autofill"
              : "Resolve review items"}
          </button>
          <button
            className="secondary"
            onClick={handleAutoApproveAll}
            disabled={
              autoApproveStatus === "running" ||
              !reviewSummary ||
              reviewRemaining === 0
            }
          >
            {autoApproveStatus === "running"
              ? "Auto-approving..."
              : "Auto-approve all & continue"}
          </button>
          <p className="note">
            {readyForAutofill
              ? "This snapshot becomes the source for autofill."
              : `Resolve ${reviewRemaining} item${reviewRemaining === 1 ? "" : "s"} to continue.`}
          </p>
        </div>
        {canonicalStatus === "error" && (
          <p className="error">Canonical approval failed. Try again after resolving issues.</p>
        )}

        {missingFields.length > 0 && !missingDismissed && (
          <div className="status missing-panel">
            <div className="missing-header">
              <div>
                <p className="status-label">Missing fields (you can fill these now)</p>
                <p className="note">
                  These values will be saved into the canonical snapshot before autofill.
                </p>
              </div>
            </div>
            <div className="missing-list">
              {missingFields.map((field) => (
                <div className="missing-row" key={`missing-${field.path}`}>
                  <div className="missing-meta">
                    <div className="field-label">{field.label}</div>
                    <div className="field-key mono">{field.path}</div>
                    {field.warning && <div className="note">{field.warning}</div>}
                  </div>
                  <div className="missing-input">{renderMissingInput(field)}</div>
                  <div className="missing-badge">
                    <span
                      className={`chip ${
                        field.required ? "chip-warning" : "chip-muted"
                      }`}
                    >
                      {field.required ? "Required" : "Optional"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
            <div className="missing-actions">
              <button
                className="primary"
                onClick={handleSaveMissingFields}
                disabled={missingSaveState === "saving"}
              >
                {missingSaveState === "saving" ? "Saving..." : "Save & re-run checks"}
              </button>
              <button
                className="secondary"
                onClick={() => setMissingDismissed(true)}
                disabled={!missingOptionalOnly}
              >
                Skip for now
              </button>
              {missingSaveState === "saved" && <span className="status-muted">Saved.</span>}
              {missingSaveError && <span className="error">{missingSaveError}</span>}
            </div>
          </div>
        )}
        {missingFields.length > 0 && missingDismissed && (
          <div className="status">
            <div className="status-row">
              <span className="status-label">Missing fields skipped for now.</span>
              <button className="ghost" onClick={() => setMissingDismissed(false)}>
                Show missing fields
              </button>
            </div>
          </div>
        )}
        {otherWarnings.length > 0 && (
          <details className="other-warnings">
            <summary>Other warnings (debug)</summary>
            <ul className="status-list">
              {otherWarnings.map((warning, idx) => (
                <li key={`${warning.code}-${idx}`}>
                  {warning.field ? `${warning.field}: ` : ""}
                  {warning.message}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      <section className="panel step-panel">
        <div className="panel-header">
          <div>
            <p className="step-eyebrow">Step 3</p>
            <h2>Autofill</h2>
            <p className="note">Uses the approved canonical fields to fill the target form.</p>
          </div>
          <div className="action-buttons">
            <button
              className="primary"
              onClick={handleAutofill}
              disabled={!canAutofill}
              title={autofillTooltip}
            >
              {pipeline.autofill === "running" ? "Autofilling..." : "Run Autofill"}
            </button>
          </div>
        </div>

        {!hasCanonical && (
          <div className="banner warning">
            Approve canonical fields in Step 2 to unlock autofill.
          </div>
        )}

        {hasCanonical && readyForAutofill && (
          <div className="status ready-panel">
            <div className="status-grid">
              <div>
                <p className="status-label">Blocking</p>
                <p className="status-value">{summarySnapshot.blocking}</p>
              </div>
              <div>
                <p className="status-label">Needs review</p>
                <p className="status-value">{summarySnapshot.needs_review}</p>
              </div>
              <div>
                <p className="status-label">Auto-approved</p>
                <p className="status-value">{summarySnapshot.auto_approved}</p>
              </div>
            </div>
            <p className="note">Ready for autofill — canonical fields approved.</p>
          </div>
        )}

        {autofillSummary && (
          <div className="status">
            {autofillSummary.error && (
              <div className="banner error">
                <div>
                  <p className="banner-title">Autofill failed</p>
                  <p className="banner-body">{autofillSummary.error}</p>
                  <div className="banner-actions">
                    <button className="ghost" onClick={handleAutofill} disabled={!canAutofill}>
                      Retry Autofill
                    </button>
                    {autofillSummary.trace_path && (
                      <button className="ghost" onClick={() => handleCopy(autofillSummary.trace_path)}>
                        Copy trace path
                      </button>
                    )}
                  </div>
                  <ul className="hint-list">
                    <li>Ensure Playwright browsers are installed.</li>
                    <li>Try again with “Show browser” enabled to observe the run.</li>
                    <li>Close any stalled Playwright windows before retrying.</li>
                  </ul>
                </div>
              </div>
            )}
            <div className="status-grid">
              <div>
                <p className="status-label">Autofill run</p>
                <p className="status-value">{autofillSummary.run_id || "—"}</p>
              </div>
              <div>
                <p className="status-label">Attempted fields</p>
                <p className="status-value">
                  {autofillSummary.attempted_fields?.length ??
                    autofillSummary.filled_fields?.length ??
                    0}
                </p>
              </div>
              <div>
                <p className="status-label">Failures</p>
                <p className="status-value">
                  {Object.keys(autofillSummary.fill_failures || {}).length}
                </p>
              </div>
            </div>
            <div className="action-row">
              <button
                className="ghost"
                onClick={handleAutofill}
                disabled={!canAutofill}
              >
                {pipeline.autofill === "running" ? "Autofilling..." : "Re-run autofill"}
              </button>
            </div>
            <div className="status-block">
              <p className="status-label">Trace</p>
              <div className="status-row">
                <span className="mono">{autofillSummary.trace_path}</span>
                <button className="ghost" onClick={() => handleCopy(autofillSummary.trace_path)}>
                  Copy
                </button>
              </div>
            </div>
            {runFolder && (
              <div className="status-block">
                <p className="status-label">Run folder</p>
                <div className="status-row">
                  <span className="mono">{runFolder}</span>
                  <button className="ghost" onClick={() => handleCopy(runFolder)}>
                    Copy
                  </button>
                </div>
                <div className="status-row">
                  <span className="mono">{runLogPath}</span>
                  <button className="ghost" onClick={() => handleCopy(runLogPath)}>
                    Copy
                  </button>
                </div>
              </div>
            )}
            {Object.keys(autofillSummary.fill_failures || {}).length > 0 && (
              <div className="status-block">
                <p className="status-label">Autofill failures (reason)</p>
                <ul className="status-list">
                  {Object.entries(autofillSummary.fill_failures || {}).map(
                    ([field, reason]) => (
                      <li key={field}>
                        <span className="mono">{field}</span> — {reason}
                      </li>
                    )
                  )}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="panel step-panel">
        <div className="panel-header">
          <div>
            <p className="step-eyebrow">Step 4</p>
            <h2>Validate</h2>
            <p className="note">
              Validate that autofill completed correctly. Rules = format/consistency, LLM = evidence check.
            </p>
          </div>
          <div className="action-buttons">
            <button
              className="primary"
              onClick={handleValidate}
              disabled={!canValidate}
              title={validateTooltip}
            >
              {pipeline.validate === "running" ? "Validating..." : "Run Validation"}
            </button>
          </div>
        </div>

        {pipeline.validate === "running" && (
          <p className="note">
            Validation running... rules check first, then LLM evidence check. This usually takes 10-20s.
          </p>
        )}
        {validationError && (
          <p className="error">Validation failed: {validationError}</p>
        )}
        {validationSummary && (
          <div className="status">
            <div className="status-grid validation-summary">
              <div>
                <p className="status-label">Fields reviewed</p>
                <p className="status-value">
                  {Object.keys(validationSummary.fields || {}).length}
                </p>
              </div>
              <div>
                <p className="status-label">Completed</p>
                <p className="status-value">{validationCounts.completed}</p>
              </div>
              <div>
                <p className="status-label">Needs human input</p>
                <p className="status-value">{validationCounts.human}</p>
              </div>
              <div>
                <p className="status-label">Needs attention</p>
                <p className="status-value">{validationCounts.needsAttention}</p>
              </div>
              <div>
                <p className="status-label">LLM used</p>
                <p className="status-value">{validationSummary.llm_used ? "Yes" : "No"}</p>
              </div>
            </div>
            <div className="queue-tabs validation-filters">
              <button
                className={`queue-tab ${validationFilter === "human" ? "active" : ""}`}
                onClick={() => setValidationFilter("human")}
              >
                Needs human ({validationCounts.human})
              </button>
              <button
                className={`queue-tab ${validationFilter === "completed" ? "active" : ""}`}
                onClick={() => setValidationFilter("completed")}
              >
                Completed ({validationCounts.completed})
              </button>
              <button
                className={`queue-tab ${validationFilter === "all" ? "active" : ""}`}
                onClick={() => setValidationFilter("all")}
              >
                All fields ({validationCounts.total})
              </button>
            </div>
            <details className="legend-details">
              <summary>Legend & definitions</summary>
              <p className="note">
                Needs human = consent/signature fields intentionally left blank. Completed = autofilled and verified.
              </p>
              <div className="legend validation-legend">
                <span className="legend-title">Status</span>
                <span className="status-chip green">OK</span>
                <span className="status-chip yellow">Needs attention</span>
                <span className="status-chip red">Missing/Invalid</span>
                <span className="status-chip unknown">Not run</span>
                <span className="status-chip yellow">Human required</span>
              </div>
              <div className="legend validation-legend">
                <span className="legend-title">Sources</span>
                <span className="chip source-mrz">MRZ</span>
                <span className="chip source-ocr">OCR</span>
                <span className="chip source-user">User</span>
                <span className="chip chip-heuristic">Evidence</span>
                <span className="chip chip-muted">No evidence</span>
              </div>
              <p className="legend-note">
                Status = final outcome. Proof = rules + LLM checks. Why = primary reason/action.
              </p>
            </details>
            {validationSummary.llm_error && (
              <details className="error-details">
                <summary>LLM error</summary>
                <p className="error">{validationSummary.llm_error}</p>
              </details>
            )}
            {formCompleteness && (
              <div className="status-block">
                <p className="status-label">Form completeness</p>
                <div className="status-row form-summary">
                  {formCompletenessItems.length ? (
                    formCompletenessItems.map((item) => (
                      <div className="form-chip" key={item.key}>
                        <span className={`status-chip ${item.tone}`}>{item.label}</span>
                        <span className="form-count">{item.count}</span>
                      </div>
                    ))
                  ) : (
                    <span className="status-muted">All required fields are filled.</span>
                  )}
                </div>
                <div className="action-row">
                  <button className="ghost" onClick={handleGoToReview}>
                    Go back to Review
                  </button>
                  <button
                    className="secondary"
                    onClick={() => setValidationAcknowledged(true)}
                    disabled={requiredMissing > 0}
                  >
                    Finish anyway
                  </button>
                </div>
                {requiredMissing > 0 ? (
                  <p className="note">
                    Resolve required form fields before finishing validation.
                  </p>
                ) : (
                  validationAcknowledged && (
                    <p className="note">Validation acknowledged.</p>
                  )
                )}
                {unmappedRequired > 0 && (
                  <details>
                    <summary>View unmapped required fields ({unmappedRequired})</summary>
                    <ul className="status-list">
                      {(formCompleteness.unmapped_required || []).map((entry, idx) => (
                        <li key={`unmapped-required-${idx}`}>
                          {entry.label || "Unmapped required field"}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            )}
            {filteredValidationRows.length > 0 && (
              <div className="table-scroll">
                <div className="table validation-table validation-table--summary">
                  <div className="table-row table-head">
                    <div>Field</div>
                    <div>Value</div>
                    <div>Status</div>
                    <div>Proof</div>
                    <div>Why</div>
                  </div>
                  {filteredValidationRows.map((row) => {
                    const status = formatValidatorVerdict(row.finalStatus || row.heuristicVerdict);
                    const heuristic = formatValidatorVerdict(row.heuristicVerdict);
                    const llmStatus =
                      row.llmInvoked && row.llmVerdict
                        ? formatValidatorVerdict(row.llmVerdict)
                        : null;
                    const sourceClass = String(row.source || "unknown")
                      .toLowerCase()
                      .replace(/[^a-z0-9_-]/g, "");
                    const heuristicReason = row.heuristicReason || "No heuristic notes.";
                    const llmJustification =
                      row.llmReason ||
                      (row.llmEvidence && row.llmEvidence !== "not found"
                        ? `Evidence: ${row.llmEvidence}`
                        : "");
                    const llmReason = row.llmInvoked
                      ? llmJustification || "No LLM explanation returned."
                      : "Not run.";
                    const humanReason = row.humanReason || "Manual input required.";
                    const humanNote = row.humanAction
                      ? `${humanReason} ${row.humanAction}`
                      : humanReason;
                    const humanType =
                      row.fieldType === "checkbox"
                        ? "Consent checkbox."
                        : row.fieldType
                        ? `${row.fieldType} field.`
                        : "";
                    const llmNeedsReview = llmStatus && llmStatus.tone !== "green";
                    const rulesNeedReview = heuristic.tone !== "green";
                    const whyText = row.requiresHuman
                      ? `${humanNote}${humanType ? ` ${humanType}` : ""}`
                      : llmNeedsReview
                      ? llmReason
                      : rulesNeedReview
                      ? heuristicReason
                      : llmJustification || "Verified by rules and LLM.";
                    return (
                      <div className="table-row" key={`validation-${row.path}`}>
                        <div>
                          <div className="field-label">{row.label}</div>
                          <div className="field-key mono">{row.path}</div>
                        </div>
                        <div className="validation-value mono">
                          {row.value}
                          <div className="validation-meta">
                            <span className={`chip source-${sourceClass}`}>{row.source}</span>
                            <span className={`chip ${row.hasEvidence ? "chip-heuristic" : "chip-muted"}`}>
                              {row.hasEvidence ? "Evidence" : "No evidence"}
                            </span>
                          </div>
                        </div>
                        <div>
                          <span className={`status-chip ${row.requiresHuman ? "yellow" : status.tone}`}>
                            {row.requiresHuman ? "Human required" : status.label}
                          </span>
                        </div>
                        <div className="validation-proof">
                          <div className="reason-line">
                            <span className="reason-label">Rules</span>
                            <span className={`status-chip ${heuristic.tone}`}>{heuristic.label}</span>
                          </div>
                          <div className="reason-line">
                            <span className="reason-label">LLM</span>
                            {row.llmInvoked ? (
                              llmStatus ? (
                                <span className={`status-chip ${llmStatus.tone}`}>{llmStatus.label}</span>
                              ) : (
                                <span className="status-muted">No verdict</span>
                              )
                            ) : (
                              <span className="status-muted">Not run</span>
                            )}
                          </div>
                        </div>
                        <div className="validation-reason">{whyText}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
