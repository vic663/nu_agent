const toneClass = {
  pass: "bg-green-100 text-green-800 border-green-200",
  fail: "bg-red-100 text-red-800 border-red-200",
  warn: "bg-amber-100 text-amber-800 border-amber-200",
  info: "bg-brand-100 text-brand-800 border-brand-200",
};

// One result card: figure on top (like a portrait), then the case, its rows and a verdict badge.
const ResultItem = ({ item }) => {
  return (
    <div className="border rounded-lg shadow-md border-stone-300 overflow-hidden bg-white p-4 flex flex-col">
      <div className="flex justify-center mb-4">
        {item.image ? (
          <img
            src={item.image}
            alt={item.title}
            className="w-full h-44 object-contain rounded-md border border-stone-200 bg-white"
          />
        ) : (
          <div className="w-full h-44 rounded-md bg-gradient-to-br from-brand-50 to-brand-100 flex items-center justify-center">
            <i className={`${item.icon} text-6xl text-brand-600`}></i>
          </div>
        )}
      </div>

      <div className="flex flex-col items-start flex-1">
        <div className="flex items-start justify-between w-full gap-2">
          <div className="text-xl font-semibold text-stone-700">{item.title}</div>
          {item.verdict && (
            <span
              className={`shrink-0 text-xs font-mono font-semibold border rounded px-2 py-0.5 mt-1 ${
                toneClass[item.tone] || toneClass.info
              }`}
            >
              {item.verdict}
            </span>
          )}
        </div>
        <div className="text-base font-sans text-stone-500">{item.subtitle}</div>

        <dl className="mt-3 w-full text-sm">
          {item.rows.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-4 py-1 border-b border-stone-100">
              <dt className="text-stone-500 shrink-0">{k}</dt>
              <dd className="text-stone-800 text-right font-mono text-xs md:text-sm">{v}</dd>
            </div>
          ))}
        </dl>

        {item.note && <p className="text-sm text-stone-600 mt-3">{item.note}</p>}
      </div>
    </div>
  );
};

export default ResultItem;
