export function formatNumber(value?: number | null) {
  if (value === undefined || value === null) {
    return "--";
  }
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function formatPercent(value?: number | null) {
  if (value === undefined || value === null) {
    return "--";
  }
  return `${value}%`;
}

export function formatDateTime(value?: string | null) {
  if (!value) {
    return "--";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatShortDate(value?: string | null) {
  if (!value) {
    return "--";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
  }).format(new Date(value));
}

export function formatMoney(value?: number | null, currency?: string | null) {
  if (value === undefined || value === null) {
    return "--";
  }
  const amount = value / 100;
  if (!currency) {
    return amount.toFixed(2);
  }
  try {
    return new Intl.NumberFormat("zh-CN", {
      style: "currency",
      currency,
      currencyDisplay: "symbol",
    }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
}

export function trendSign(delta?: number | null) {
  if (delta === undefined || delta === null || delta === 0) {
    return "--";
  }
  return delta > 0 ? `+${formatNumber(delta)}` : formatNumber(delta);
}
