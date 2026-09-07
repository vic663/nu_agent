import CapabilityItem from "./PageCapabilities/CapabilityItem";
import CapabilityData from "./PageCapabilities/CapabilityData";

const PageCapabilities = () => {
  const workflowItems = CapabilityData.filter((item) => item.group === "workflow");
  const platformItems = CapabilityData.filter((item) => item.group === "platform");

  return (
    <div className="space-y-8 p-6 flex flex-col max-w-6xl mx-auto">
      <div>
        <h1 className="text-4xl font-bold text-brand-700 mb-2 font-serif_title">Capabilities</h1>
        <p className="font-lato text-stone-600">
          Each node of the workflow graph, then the solvers, executors and policies it drives.
        </p>
      </div>

      <h2 className="text-2xl font-semibold text-brand-700 mb-4 font-serif_title">
        Workflow nodes
        <span className="block font-mono text-xs md:text-sm font-normal text-stone-500 mt-2">
          plan → review → build → run → monitor → postprocess → verify → model_form → validate → calibrate → uq → critique → report
        </span>
      </h2>
      {workflowItems.map((item) => (
        <CapabilityItem
          key={item.id}
          tag={item.tag}
          title={item.title}
          description={item.description}
          image={item.image}
          icon={item.icon}
        />
      ))}

      <h2 className="text-2xl font-semibold text-brand-700 mt-8 mb-4 font-serif_title">
        Backends, executors, policies and qualification
      </h2>
      {platformItems.map((item) => (
        <CapabilityItem
          key={item.id}
          tag={item.tag}
          title={item.title}
          description={item.description}
          image={item.image}
          icon={item.icon}
        />
      ))}
    </div>
  );
};

export default PageCapabilities;
