const fs = require('fs');
const content = fs.readFileSync('src/App.jsx', 'utf8');

let balance = 0;
let inString = false;
let stringChar = '';
let inTemplate = false;
let inSingleLineComment = false;
let inMultiLineComment = false;

for (let i = 0; i < content.length; i++) {
  const c = content[i];
  const next = content[i + 1];
  
  // Handle comments
  if (!inString && !inTemplate) {
    if (!inMultiLineComment && c === '/' && next === '/') {
      inSingleLineComment = true;
      continue;
    }
    if (!inSingleLineComment && c === '/' && next === '*') {
      inMultiLineComment = true;
      i++; // skip *
      continue;
    }
    if (inMultiLineComment && c === '*' && next === '/') {
      inMultiLineComment = false;
      i++; // skip /
      continue;
    }
    if (inSingleLineComment && c === '\n') {
      inSingleLineComment = false;
    }
    
    if (inSingleLineComment || inMultiLineComment) continue;
  }
  
  // Handle strings and templates
  if (!inString && !inTemplate) {
    if (c === '"' || c === "'") {
      inString = true;
      stringChar = c;
    } else if (c === '`') {
      inTemplate = true;
    } else if (c === '{') {
      balance++;
    } else if (c === '}') {
      balance--;
      if (balance < 0) {
        const lineNum = content.substring(0, i).split('\n').length;
        console.log('Negative balance at position', i, 'line', lineNum);
        const start = Math.max(0, i - 100);
        const end = Math.min(content.length, i + 50);
        console.log('Context:', JSON.stringify(content.substring(start, end)));
        break;
      }
    }
  } else if (inString && c === stringChar && content[i - 1] !== '\\') {
    inString = false;
  } else if (inTemplate && c === '`') {
    inTemplate = false;
  }
}

console.log('Final balance:', balance);