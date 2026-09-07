// One capability card: figure (or a large icon when there is no figure) on the left, text on the right.
const CapabilityItem = ({ tag, title, description, image, icon }) => {
  return (
    <div className="flex flex-col md:flex-row items-center gap-6 p-4 border border-stone-200 rounded-lg shadow-md bg-white">
      <div className="flex-shrink-0 w-full md:w-1/2">
        {image ? (
          <img src={image} alt={title} className="w-full h-auto object-contain rounded-md" />
        ) : (
          <div className="w-full aspect-[16/7] rounded-md bg-gradient-to-br from-brand-50 to-brand-100 flex items-center justify-center">
            <i className={`${icon} text-6xl md:text-7xl text-brand-600`}></i>
          </div>
        )}
      </div>

      <div className="flex-1 text-left md:pl-6">
        {tag && (
          <span className="inline-block text-xs font-mono uppercase tracking-wide text-brand-700 bg-brand-50 border border-brand-200 rounded px-2 py-0.5 mb-2">
            {tag}
          </span>
        )}
        <h2 className="text-lg font-semibold mb-2 text-stone-800">{title}</h2>
        <p className="text-sm text-stone-600">{description}</p>
      </div>
    </div>
  );
};

export default CapabilityItem;
