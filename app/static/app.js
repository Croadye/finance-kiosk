document.addEventListener('DOMContentLoaded', () => {
    const amountInput = document.querySelector('#amount');
    document.querySelectorAll('.nkey').forEach(btn => {
        btn.addEventListener('click', () => {
            const key = btn.dataset.key;
            if (!amountInput) return;
            if (key === 'C') {
                amountInput.value = '';
                return;
            }
            if (key === '.' && amountInput.value.includes('.')) return;
            amountInput.value = (amountInput.value || '') + key;
        });
    });
});
