import { useNavigate } from 'react-router-dom';

const Companies = ({ companies = [] }) => {
  const navigate = useNavigate();

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {companies.map((company) => (
        <div key={company.id} className="bg-gray-900 rounded-2xl p-6 border border-gray-800 hover:border-blue-500 transition-all">
          <h3 className="text-xl font-bold">{company.name}</h3>
          <p className="text-gray-400 mt-2">{company.description || 'Egg study company'}</p>
          
          <div className="mt-6 flex gap-4">
            <button 
              onClick={() => navigate(`/companies/${company.id}`)}
              className="flex-1 py-3 bg-blue-600 hover:bg-blue-700 rounded-xl font-semibold"
            >
              View Full Study
            </button>
            <button className="flex-1 py-3 bg-gray-800 hover:bg-gray-700 rounded-xl font-semibold">
              Quick View
            </button>
          </div>
        </div>
      ))}
    </div>
  );
};

export default Companies;
