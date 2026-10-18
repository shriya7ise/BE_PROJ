const ExportProgress = ({ exporting }) => {
  if (!exporting) return null;
  return <div className="fixed bottom-4 right-4 bg-blue-600 text-white px-6 py-3 rounded-2xl">Generating PDF...</div>;
};

export default ExportProgress;
