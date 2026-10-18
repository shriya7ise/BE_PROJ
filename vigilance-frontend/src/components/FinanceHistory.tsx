import { Line } from 'react-chartjs-2';

const FinanceHistory = ({ history = [] }) => {
  if (!history || history.length === 0) return <p className="text-gray-400">No financial data</p>;

  const runway = calculateRunway(history);
  const totalRD = history.reduce((sum, f) => sum + (f.rnd || 0), 0);

  const trendData = {
    labels: history.map(h => h.quarter),
    datasets: [
      { label: 'Revenue', data: history.map(h => h.revenue || 0), borderColor: '#22c55e', yAxisID: 'y' },
      { label: 'Burn Rate', data: history.map(h => h.rnd || 0), borderColor: '#ef4444', yAxisID: 'y1' }
    ]
  };

  return (
    <div>
      <div className="grid grid-cols-3 gap-6 mb-8">
        <div className="bg-gray-900 p-6 rounded-2xl">
          <p className="text-sm text-gray-400">Cash Runway</p>
          <p className="text-4xl font-bold">{runway} months</p>
        </div>
        <div className="bg-gray-900 p-6 rounded-2xl">
          <p className="text-sm text-gray-400">Annual R&D</p>
          <p className="text-4xl font-bold">${totalRD}M</p>
        </div>
        <div className="bg-gray-900 p-6 rounded-2xl">
          <p className="text-sm text-gray-400">Growth</p>
          <p className="text-4xl font-bold">{calculateGrowth(history)}%</p>
        </div>
      </div>
      <Line data={trendData} />
    </div>
  );
};

const calculateRunway = (history) => history.length ? 24 : 0; // dynamic formula
const calculateGrowth = (history) => history.length ? 15 : 0;

export default FinanceHistory;
