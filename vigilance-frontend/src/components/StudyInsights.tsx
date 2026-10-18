import { Line, Pie } from 'react-chartjs-2';

const StudyInsights = ({ studies = [] }) => {
  if (!studies || studies.length === 0) return <p className="text-gray-400">No egg studies available</p>;

  const avgTimeline = studies.reduce((sum, s) => sum + (s.durationMonths || 0), 0) / studies.length;
  const successRate = studies.filter(s => s.success).length / studies.length * 100;

  const timelineData = {
    labels: studies.map(s => s.phase || 'Phase ' + s.id),
    datasets: [{
      label: 'Months',
      data: studies.map(s => s.durationMonths || 0),
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59, 130, 246, 0.2)'
    }]
  };

  const resourceData = {
    labels: ['R&D', 'Clinical', 'Marketing', 'Other'],
    datasets: [{
      data: studies.reduce((acc, s) => {
        acc['R&D'] = (acc['R&D'] || 0) + (s.spentOnResearch || 0);
        acc['Clinical'] = (acc['Clinical'] || 0) + (s.spentOnClinical || 0);
        acc['Marketing'] = (acc['Marketing'] || 0) + (s.spentOnMarketing || 0);
        acc['Other'] = (acc['Other'] || 0) + (s.otherSpent || 0);
        return acc;
      }, {})
    }]
  };

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
        <div className="bg-gray-900 p-6 rounded-2xl">
          <p className="text-sm text-gray-400">Total Studies</p>
          <p className="text-4xl font-bold">{studies.length}</p>
        </div>
        <div className="bg-gray-900 p-6 rounded-2xl">
          <p className="text-sm text-gray-400">Avg Timeline</p>
          <p className="text-4xl font-bold">{avgTimeline.toFixed(1)} months</p>
        </div>
        <div className="bg-gray-900 p-6 rounded-2xl">
          <p className="text-sm text-gray-400">Success Rate</p>
          <p className="text-4xl font-bold">{successRate.toFixed(1)}%</p>
        </div>
        <div className="bg-gray-900 p-6 rounded-2xl">
          <p className="text-sm text-gray-400">Total Spend</p>
          <p className="text-4xl font-bold">${(studies.reduce((sum, s) => sum + (s.spent || 0), 0) / 12).toFixed(1)}M/year</p>
        </div>
      </div>

      <div>
        <h3 className="text-xl mb-4">Trial Timeline</h3>
        <Line data={timelineData} />
      </div>
      <div>
        <h3 className="text-xl mb-4">Resource Allocation</h3>
        <Pie data={resourceData} />
      </div>
    </div>
  );
};

export default StudyInsights;
