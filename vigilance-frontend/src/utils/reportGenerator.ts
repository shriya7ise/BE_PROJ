import jsPDF from 'jspdf';

export const exportStudyReport = (company, studies) => {
  const doc = new jsPDF();
  doc.setFontSize(20);
  doc.text(`${company.name} - Egg Study Report`, 20, 20);
  doc.text(`Generated: ${new Date().toLocaleDateString()}`, 20, 30);
  doc.text(`Total Studies: ${studies.length}`, 20, 40);
  doc.save(`${company.name}-Study-Report.pdf`);
};

export const exportFinanceReport = (company, history) => {
  const doc = new jsPDF();
  doc.setFontSize(20);
  doc.text(`${company.name} - Finance Report`, 20, 20);
  doc.text(`Generated: ${new Date().toLocaleDateString()}`, 20, 30);
  doc.text(`Runway: ${history.length ? '24 months' : 'N/A'}`, 20, 40);
  doc.save(`${company.name}-Finance-Report.pdf`);
};
