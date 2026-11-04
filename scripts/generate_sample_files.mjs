import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { markdownToHwpx } from "kordoc";


const samples = [
  ["i_1.hwpx", "I-1 에너지 정책 추진현황", "에너지정책팀", "청정에너지 전환 기반을 강화하고 지역 에너지 정책을 체계적으로 추진합니다."],
  ["i_2.hwpx", "I-2 에너지 정책 주요과제", "에너지정책팀", "정책 이행점검과 유관기관 협업체계를 운영합니다."],
  ["ii_1.hwpx", "II-1 재생에너지 확대", "재생에너지팀", "지역 여건에 맞는 재생에너지 보급사업을 확대합니다."],
  ["ii_2.hwpx", "II-2 해상풍력 추진", "재생에너지팀", "주민수용성과 계통여건을 고려한 해상풍력 사업을 지원합니다."],
  ["iii_1.hwpx", "III-1 수소산업 육성", "수소산업팀", "수소기업 성장과 기술사업화를 위한 지원체계를 마련합니다."],
  ["iii_2.hwpx", "III-2 수소 인프라 구축", "수소산업팀", "안전한 수소 생산·저장·활용 인프라를 단계적으로 구축합니다."],
  ["iv_1.hwpx", "IV-1 에너지 관리", "에너지관리팀", "안정적인 에너지 공급과 시설 안전관리를 강화합니다."],
  ["iv_2.hwpx", "IV-2 에너지 효율화", "에너지관리팀", "공공·민간 부문의 에너지 효율 개선사업을 추진합니다."],
  ["v_1.hwpx", "V-1 RE100 지원", "RE100팀", "기업의 재생에너지 전환계획 수립과 이행을 지원합니다."],
  ["v_2.hwpx", "V-2 기업 RE100 확산", "RE100팀", "산업단지와 공급망을 중심으로 RE100 참여 기반을 확대합니다."],
];


const outputDir = resolve("sample_files");
await mkdir(outputDir, { recursive: true });
for (const [filename, title, team, body] of samples) {
  const markdown = [
    "# " + title,
    "",
    "담당팀: " + team,
    "",
    "## 추진방향",
    body,
    "",
    "## 주요내용",
    "",
    "| 구분 | 내용 |",
    "| --- | --- |",
    "| 담당 | " + team + " |",
    "| 자료구분 | 전산부서 시연용 가상자료 |",
  ].join("\n");
  const buffer = await markdownToHwpx(markdown, { gongmun: { preset: "보고서" } });
  await writeFile(resolve(outputDir, filename), Buffer.from(buffer));
}
console.log(samples.length + "개 HWPX 샘플을 생성했습니다.");

