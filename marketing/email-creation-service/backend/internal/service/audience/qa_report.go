package audience

import (
	"bytes"
	"strconv"

	"github.com/xuri/excelize/v2"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain/model"
)

var itoa = strconv.Itoa

// verdictFillColor mirrors qa_report.py's _VERDICT_FILL: green PASS / red
// FAIL / amber NEEDS VERIFY, no fill for anything else.
var verdictFillColor = map[string]string{
	"PASS":         "C6EFCE",
	"FAIL":         "FFC7CE",
	"NEEDS VERIFY": "FFEB9C",
}

var checkLabels = []struct{ key, label string }{
	{"signal_mapping", "Source List Signal Mapping"},
	{"gdpr_casl_suppression", "GDPR & Regional Suppression"},
	{"exclusion_completeness", "Exclusion Completeness"},
}

// BuildQaWorkbook builds a downloadable XLSX QA report from RunQaOnList's
// result — same verdict-color-coding convention as the audience-qa skill's
// own report format, scoped to a single list.
func BuildQaWorkbook(result *model.QaResult) ([]byte, error) {
	f := excelize.NewFile()
	defer f.Close()

	const summarySheet = "Executive Summary"
	f.SetSheetName("Sheet1", summarySheet)

	headerStyle, err := f.NewStyle(&excelize.Style{
		Fill:      excelize.Fill{Type: "pattern", Color: []string{"1F4E79"}, Pattern: 1},
		Font:      &excelize.Font{Color: "FFFFFF", Bold: true},
		Alignment: &excelize.Alignment{Vertical: "center", WrapText: true},
	})
	if err != nil {
		return nil, err
	}

	verdictStyle := func(verdict string) (int, error) {
		color, ok := verdictFillColor[verdict]
		if !ok {
			return -1, nil
		}
		return f.NewStyle(&excelize.Style{Fill: excelize.Fill{Type: "pattern", Color: []string{color}, Pattern: 1}})
	}

	f.SetCellValue(summarySheet, "A1", "List Name")
	f.SetCellValue(summarySheet, "B1", result.Name)
	f.SetCellValue(summarySheet, "A2", "List ID")
	f.SetCellValue(summarySheet, "B2", result.ListID)
	f.SetCellValue(summarySheet, "A3", "HubSpot URL")
	f.SetCellValue(summarySheet, "B3", result.HubSpotURL)
	f.SetCellValue(summarySheet, "A4", "Overall Verdict")
	f.SetCellValue(summarySheet, "B4", result.Overall)
	if style, err := verdictStyle(result.Overall); err != nil {
		return nil, err
	} else if style != -1 {
		f.SetCellStyle(summarySheet, "B4", "B4", style)
	}

	f.SetCellValue(summarySheet, "A6", "Check")
	f.SetCellValue(summarySheet, "B6", "Verdict")
	f.SetCellStyle(summarySheet, "A6", "B6", headerStyle)

	row := 7
	for _, cl := range checkLabels {
		verdict := result.Checks[cl.key].Verdict
		cell := "B" + itoa(row)
		f.SetCellValue(summarySheet, "A"+itoa(row), cl.label)
		f.SetCellValue(summarySheet, cell, verdict)
		if style, err := verdictStyle(verdict); err != nil {
			return nil, err
		} else if style != -1 {
			f.SetCellStyle(summarySheet, cell, cell, style)
		}
		row++
	}
	f.SetColWidth(summarySheet, "A", "A", 32)
	f.SetColWidth(summarySheet, "B", "B", 40)

	const findingsSheet = "Findings"
	f.NewSheet(findingsSheet)
	f.SetCellValue(findingsSheet, "A1", "Severity")
	f.SetCellValue(findingsSheet, "B1", "Message")
	f.SetCellValue(findingsSheet, "C1", "Fix")
	f.SetCellStyle(findingsSheet, "A1", "C1", headerStyle)

	wrapStyle, err := f.NewStyle(&excelize.Style{Alignment: &excelize.Alignment{WrapText: true, Vertical: "top"}})
	if err != nil {
		return nil, err
	}
	for i, finding := range result.Findings {
		r := i + 2
		f.SetCellValue(findingsSheet, "A"+itoa(r), finding.Severity)
		f.SetCellValue(findingsSheet, "B"+itoa(r), finding.Message)
		f.SetCellValue(findingsSheet, "C"+itoa(r), finding.Fix)
		f.SetCellStyle(findingsSheet, "A"+itoa(r), "C"+itoa(r), wrapStyle)
	}
	f.SetColWidth(findingsSheet, "A", "A", 12)
	f.SetColWidth(findingsSheet, "B", "B", 60)
	f.SetColWidth(findingsSheet, "C", "C", 60)

	f.SetActiveSheet(0)

	var buf bytes.Buffer
	if _, err := f.WriteTo(&buf); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}
