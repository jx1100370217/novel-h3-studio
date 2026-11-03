const path = require('path');

module.exports = {
  mode: 'production',
  entry: path.resolve(__dirname, 'board.js'),
  output: {
    path: __dirname,
    filename: 'board.bundle.js',
  },
  optimization: { minimize: true },
  devtool: false,
};
