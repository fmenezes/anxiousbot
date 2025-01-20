function log(level: string, msg: string) {
  let logs = document.querySelector('#logs');
  if (logs == null) {
    return;
  }
  logs.innerHTML = `<p class="read-the-docs">[${level}] ${msg.replaceAll("\n", "<br />")}</p>\n` + logs.innerHTML;
}

function info(msg: string) {
  return log('INFO', msg);
}

function error(msg: string) {
  return log('ERROR', msg);
}

import { Connection, PublicKey, TransactionResponse } from "@solana/web3.js";

const url = "https://broken-autumn-ensemble.solana-mainnet.quiknode.pro/caf127f77fcfbd4d441b47a01176249b96c238a7/";

// Solana connection
// Program IDs for Solana DEXes
const dexProgramIds: Record<string, string> = {
  Raydium: "4cKxjvnxMw2KjyUbkXuxD6gZnn9i9okRyr6Xkkz4mFw5",
  Orca: "9WZkgPZYmCFbTKPKmfZGdX4L49vHtNAYETQfjtrKkD5e",
};

// Fetch recent transactions from a program
async function getRecentTransactions(connection: Connection, programId: string, limit: number = 1000) {
  const programPublicKey = new PublicKey(programId);
  const signatures = await connection.getSignaturesForAddress(programPublicKey, { limit });
  return signatures;
}

// Fetch and decode transaction details
async function getTransactionDetails(connection: Connection, signature: string) {
  const transactionDetails = await connection.getTransaction(signature, {
    commitment: "confirmed"
  });
  return transactionDetails;
}

// Analyze transactions for pool creation
function extractPoolCreationInfo(transaction: TransactionResponse | null, dexName: string) {
  if (!transaction) {
    info(`[${dexName}] Invalid transaction data.`);
    return;
  }

  const instructions = transaction.transaction.message.instructions;

  instructions.forEach((instruction: any) => {
    const programId = new PublicKey(instruction.programId).toString();

    if (programId === dexProgramIds[dexName]) {
      info(`[${dexName}] Instruction detected: ` + JSON.stringify(instruction));
      // You need to parse instruction data here to identify pool creation logic
    }
  });
}

// Main function to get DEX pools
async function getDexPools(connection: Connection) {
  for (const [dexName, programId] of Object.entries(dexProgramIds)) {
    info(`Checking for ${dexName} Pools...`);
    const transactions = await getRecentTransactions(connection, programId, 5);

    for (const tx of transactions) {
      info(`${dexName} Transaction: ${tx.signature}`);
      const txDetails = await getTransactionDetails(connection, tx.signature);
      extractPoolCreationInfo(txDetails, dexName);
    }
  }
}

function delay(ms: number) {
    return new Promise( resolve => setTimeout(resolve, ms) );
}

try {
  const connection = new Connection(url);

  info(`connecting...`);
  info(`slot: ${await connection.getSlot()}`);
  info(`connected`);

  // Start the process
  while (true) {
    try {
      await getDexPools(connection)
    } catch(err: any) {
      error(err.message + "\n" + err.stack);
    }
    await delay(1000);
  }

} catch(err: any) {
  error(err.message + "\n" + err.stack);
}
