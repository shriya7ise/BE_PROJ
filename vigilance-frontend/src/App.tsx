import { useState, useEffect } from 'react';
import Companies from './components/Companies';

const App = () => {
  const [companies, setCompanies] = useState([]);

  useEffect(() => {
    fetch('/api/companies').then(r => r.json()).then(setCompanies);
  }, []);

  return (
    <div className="p-8">
      <h1 className="text-4xl font-bold mb-8">Companies</h1>
      <Companies companies={companies} />
    </div>
  );
};

export default App;
